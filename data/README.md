# Data

## Vulnerability slice

`vuln/claims.jsonl` is a processed slice of multi-source vulnerability claims scored against a manual gold set. The benchmark reads this file. It does not download during a run.

Gold: [Zenodo 16440960](https://doi.org/10.5281/zenodo.16440960), CC BY 4.0. Dataset for "Vulnerability-Affected Versions Identification: How Far Are We?" 1,128 CVEs and the manually listed affected upstream tags (FFmpeg, linux, curl, openssl, qemu, httpd, ImageMagick, wireshark, openjpeg). A tag is not-affected when it appears on that repository in the gold file and is not in that CVE's affected list.

Sources, each a separate voter:

| Source | Feed |
|---|---|
| nvd | [CVE-to-OSV conversion](https://storage.googleapis.com/cve-osv-conversion/osv-output/) CPE ranges |
| debian, alpine, redhat, linux, alma, opensuse, suse, mageia, rocky | [OSV ecosystem zips](https://google.github.io/osv.dev/data/) |

Ubuntu's OSV zip is 816 MB and is not included; Debian is the Debian-family feed. The combined OSV `all.zip` (about 3 GB) is not downloaded. GitHub Advisory API records for these CVEs did not include package version ranges, so GHSA is not a voter. CISA KEV has no version ranges, so it is not a voter.

Sampling, seed 0: at most 40 CVEs per repository, at most 3 affected and 3 unaffected tags per CVE, and only questions where at least two sources cast a verdict. Checksums are in `vuln/slice.json`. Regenerate with `python scripts/fetch_vuln.py`.

Version comparison keeps up to six numeric components, ignores git commit ids, and treats an OSV `introduced` / `fixed` pair the usual way: a version is affected from `introduced` inclusive until `fixed` exclusive. An explicit version list counts as a hit when the numeric key matches, and as a miss when the feed enumerated versions and this tag was not among them.

## Book slice

`book/` is the earlier bookseller cache. The dashboard and the benchmark no longer read it.
