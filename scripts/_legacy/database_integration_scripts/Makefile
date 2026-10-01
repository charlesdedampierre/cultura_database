CC = gcc
CFLAGS = -O3 -Wall
LDFLAGS = -lsqlite3

all: clean_sqlite enhance_sqlite fix_encoding clean_dates add_counts add_date_precision

clean_sqlite: clean_sqlite.c
	$(CC) $(CFLAGS) -o $@ $< $(LDFLAGS)

enhance_sqlite: enhance_sqlite.c
	$(CC) $(CFLAGS) -o $@ $< $(LDFLAGS)

fix_encoding: fix_encoding.c
	$(CC) $(CFLAGS) -o $@ $< $(LDFLAGS)

clean_dates: clean_dates.c
	$(CC) $(CFLAGS) -o $@ $< $(LDFLAGS)

add_counts: add_counts.c
	$(CC) $(CFLAGS) -o $@ $< $(LDFLAGS)

add_date_precision: add_date_precision.c
	$(CC) $(CFLAGS) -o $@ $< $(LDFLAGS)

run: clean_sqlite
	./clean_sqlite ../data/all_humans/humans.sqlite3 ../data/all_humans/humans_clean.sqlite3

enhance: enhance_sqlite
	./enhance_sqlite ../data/all_humans/humans_clean.sqlite3 ../data/all_humans

# Individual steps
fix: fix_encoding
	./fix_encoding ../data/all_humans/humans_clean.sqlite3

dates: clean_dates
	./clean_dates ../data/all_humans/humans_clean.sqlite3

counts: add_counts
	./add_counts ../data/all_humans/humans_clean.sqlite3

precision: add_date_precision
	./add_date_precision ../data/all_humans/humans_final.sqlite3 ../data/all_humans/all_human_date_precision.json

clean:
	rm -f clean_sqlite enhance_sqlite fix_encoding clean_dates add_counts add_date_precision

.PHONY: all run enhance fix dates counts precision clean
