from dreamgraph.store import ObjectStore


def test_put_get_roundtrip_uses_the_bucket_not_a_file(tmp_path):
    store = ObjectStore(bucket="dreamgraph-test", use_moto=True)
    try:
        store.put_json("results/summary.json", {"accuracy": 0.5, "backend": "memory"})
        assert store.get_json("results/summary.json")["accuracy"] == 0.5
        # A second client against the same moto process still sees the object.
        again = store.client.get_object(Bucket=store.bucket, Key="results/summary.json")
        assert b"memory" in again["Body"].read()
        exported = store.export_json("results/summary.json", tmp_path / "summary.json")
        assert exported.exists()
        assert "memory" in exported.read_text()
    finally:
        store.close()


def test_restart_is_a_new_client_against_the_same_bucket():
    store = ObjectStore(bucket="dreamgraph-restart", use_moto=True)
    try:
        store.put_json("probe/before.json", {"name": "before-restart"})
        import boto3

        restarted = boto3.client(
            "s3",
            region_name="us-east-1",
            aws_access_key_id="testing",
            aws_secret_access_key="testing",
        )
        body = restarted.get_object(Bucket="dreamgraph-restart", Key="probe/before.json")
        assert b"before-restart" in body["Body"].read()
        restarted.put_object(
            Bucket="dreamgraph-restart",
            Key="probe/after.json",
            Body=b'{"name": "after-restart"}',
        )
        assert store.get_json("probe/after.json")["name"] == "after-restart"
        assert store.get_json("probe/before.json")["name"] == "before-restart"
    finally:
        store.close()
