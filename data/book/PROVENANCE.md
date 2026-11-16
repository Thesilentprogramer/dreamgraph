# Book seller slice

Processed cache of the Book data set distributed for research use at
[lunadong.com/fusionDataSets.htm](https://lunadong.com/fusionDataSets.htm).

- Claims: Xiaoxin Yin, Jiawei Han, and Philip S. Yu. Truth discovery with multiple conflicting information providers on the web. IEEE TKDE, 2008.
- Gold author lists (book covers, 100 ISBNs): Xin Luna Dong, Laure Berti-Equille, and Divesh Srivastava. Integrating conflicting data: the role of source dependence. VLDB, 2009.

`claims.jsonl` keeps one listing per ISBN per seller for three booksellers that each cover many of those gold ISBNs: Revaluation Books, The Book Depository, and textbooksNow. Books with fewer than two of those sellers are dropped, so every question has a disagreement to resolve. Author strings, ISBNs, and seller names are the facts the benchmark scores. Titles are display labels.

Upstream checksums (sha256):

- `book.zip`: `2967800b3bf99eebd25807b8f28dea77c64d93a574806fe82d76e548642c6e65`
- `book_golden.txt`: `7b05f0b1b96bb0d264b4e4ce2ce9175225fb877e02a93e984233b20643b84fcd`

Regenerate with `python scripts/fetch_book.py`. The benchmark reads this file and does not download during a run.
