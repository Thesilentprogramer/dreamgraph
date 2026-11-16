from dreamgraph.moto_state import restore_bucket, snapshot_bucket
from dreamgraph.store import ObjectStore


def test_snapshot_round_trip_reloads_the_bucket(tmp_path):
    store = ObjectStore(bucket="dreamgraph-state", use_moto=True)
    try:
        store.put_json("graphs/cell.json", {"name": "kept"})
        written = snapshot_bucket(store.client, store.bucket, tmp_path)
        assert written == 1
        store.client.delete_object(Bucket=store.bucket, Key="graphs/cell.json")
        restored = restore_bucket(store.client, store.bucket, tmp_path)
        assert restored == 1
        assert store.get_json("graphs/cell.json")["name"] == "kept"
    finally:
        store.close()
