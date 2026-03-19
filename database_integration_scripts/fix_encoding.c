/*
 * Fix double UTF-8 encoding in SQLite database (in-place UPDATE)
 * gcc -O3 -o fix_encoding fix_encoding.c -lsqlite3
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <sqlite3.h>

#define MAX_STR 65536
#define BATCH 50000

typedef struct {
    sqlite3_int64 rowid;
    char* fixed_value;
} Fix;

static Fix* fixes = NULL;
static size_t fixes_count = 0;
static size_t fixes_cap = 0;

static void add_fix(sqlite3_int64 rowid, const char* val) {
    if (fixes_count >= fixes_cap) {
        fixes_cap = fixes_cap ? fixes_cap * 2 : 100000;
        fixes = realloc(fixes, fixes_cap * sizeof(Fix));
    }
    fixes[fixes_count].rowid = rowid;
    fixes[fixes_count].fixed_value = strdup(val);
    fixes_count++;
}

static void clear_fixes() {
    for (size_t i = 0; i < fixes_count; i++) free(fixes[fixes_count].fixed_value);
    fixes_count = 0;
}

static int has_mojibake(const char* s) {
    const unsigned char* p = (const unsigned char*)s;
    while (*p) {
        if (p[0] == 0xC3 && p[1] >= 0x80 && p[1] <= 0xBF) return 1;
        if (p[0] == 0xC2 && p[1] >= 0x80 && p[1] <= 0xBF) return 1;
        p++;
    }
    return 0;
}

static int is_valid_utf8(const unsigned char* s, size_t len) {
    for (size_t i = 0; i < len;) {
        if (s[i] < 0x80) i++;
        else if ((s[i] & 0xE0) == 0xC0 && i+1 < len && (s[i+1] & 0xC0) == 0x80) i += 2;
        else if ((s[i] & 0xF0) == 0xE0 && i+2 < len) i += 3;
        else if ((s[i] & 0xF8) == 0xF0 && i+3 < len) i += 4;
        else return 0;
    }
    return 1;
}

static int fix_utf8(const char* in, char* out, size_t max) {
    if (!in || !has_mojibake(in)) { strcpy(out, in ? in : ""); return 0; }

    unsigned char tmp[MAX_STR];
    size_t len = 0;
    const unsigned char* p = (const unsigned char*)in;

    while (*p && len < MAX_STR - 1) {
        uint32_t cp; int skip;
        if ((*p & 0x80) == 0) { cp = *p; skip = 1; }
        else if ((*p & 0xE0) == 0xC0) { cp = ((*p & 0x1F) << 6) | (p[1] & 0x3F); skip = 2; }
        else if ((*p & 0xF0) == 0xE0) { cp = ((*p & 0x0F) << 12) | ((p[1] & 0x3F) << 6) | (p[2] & 0x3F); skip = 3; }
        else if ((*p & 0xF8) == 0xF0) { cp = ((*p & 0x07) << 18) | ((p[1] & 0x3F) << 12) | ((p[2] & 0x3F) << 6) | (p[3] & 0x3F); skip = 4; }
        else { tmp[len++] = *p++; continue; }

        if (cp < 256) tmp[len++] = (unsigned char)cp;
        else { strcpy(out, in); return 0; }
        p += skip;
    }
    tmp[len] = '\0';

    if (is_valid_utf8(tmp, len)) { memcpy(out, tmp, len + 1); return 1; }
    strcpy(out, in);
    return 0;
}

int main(int argc, char* argv[]) {
    if (argc != 2) { fprintf(stderr, "Usage: %s <database.sqlite3>\n", argv[0]); return 1; }

    sqlite3 *db;
    int rc = sqlite3_open(argv[1], &db);
    if (rc != SQLITE_OK) { fprintf(stderr, "Cannot open DB: %s\n", sqlite3_errmsg(db)); return 1; }

    sqlite3_exec(db, "PRAGMA synchronous=OFF;", NULL, NULL, NULL);
    sqlite3_exec(db, "PRAGMA journal_mode=DELETE;", NULL, NULL, NULL);
    sqlite3_exec(db, "PRAGMA cache_size=100000;", NULL, NULL, NULL);

    const char* cols[] = {"name_en", "description_en", "nationalities_en", "birthcity_en", "deathcity_en", "occupations_en", NULL};
    char buffer[MAX_STR];

    for (int c = 0; cols[c]; c++) {
        printf("Fixing %s...\n", cols[c]); fflush(stdout);

        /* Phase 1: Read and collect fixes */
        printf("  Scanning...\n"); fflush(stdout);
        char sql[512];
        snprintf(sql, sizeof(sql), "SELECT rowid, %s FROM individuals WHERE %s IS NOT NULL", cols[c], cols[c]);

        sqlite3_stmt *sel;
        rc = sqlite3_prepare_v2(db, sql, -1, &sel, NULL);
        if (rc != SQLITE_OK) { fprintf(stderr, "Prepare error: %s\n", sqlite3_errmsg(db)); continue; }

        long total = 0;
        fixes_count = 0;

        while (sqlite3_step(sel) == SQLITE_ROW) {
            total++;
            const char* val = (const char*)sqlite3_column_text(sel, 1);
            if (val && fix_utf8(val, buffer, sizeof(buffer))) {
                add_fix(sqlite3_column_int64(sel, 0), buffer);
            }
            if (total % 500000 == 0) { printf("\r  Scanned %ld rows, found %zu to fix...", total, fixes_count); fflush(stdout); }
        }
        sqlite3_finalize(sel);
        printf("\r  Scanned %ld rows, found %zu to fix    \n", total, fixes_count); fflush(stdout);

        if (fixes_count == 0) {
            printf("  ✓ Nothing to fix\n");
            continue;
        }

        /* Phase 2: Apply fixes */
        printf("  Applying %zu fixes...\n", fixes_count); fflush(stdout);

        snprintf(sql, sizeof(sql), "UPDATE individuals SET %s=? WHERE rowid=?", cols[c]);
        sqlite3_stmt *upd;
        rc = sqlite3_prepare_v2(db, sql, -1, &upd, NULL);
        if (rc != SQLITE_OK) { fprintf(stderr, "Prepare error: %s\n", sqlite3_errmsg(db)); continue; }

        sqlite3_exec(db, "BEGIN TRANSACTION;", NULL, NULL, NULL);

        for (size_t i = 0; i < fixes_count; i++) {
            sqlite3_bind_text(upd, 1, fixes[i].fixed_value, -1, SQLITE_STATIC);
            sqlite3_bind_int64(upd, 2, fixes[i].rowid);
            rc = sqlite3_step(upd);
            if (rc != SQLITE_DONE) {
                fprintf(stderr, "Update error at %zu: %s\n", i, sqlite3_errmsg(db));
            }
            sqlite3_reset(upd);

            if ((i + 1) % BATCH == 0) {
                sqlite3_exec(db, "COMMIT;", NULL, NULL, NULL);
                printf("\r  Applied %zu/%zu fixes...", i + 1, fixes_count); fflush(stdout);
                sqlite3_exec(db, "BEGIN TRANSACTION;", NULL, NULL, NULL);
            }
        }

        sqlite3_exec(db, "COMMIT;", NULL, NULL, NULL);
        sqlite3_finalize(upd);

        /* Free fix strings */
        for (size_t i = 0; i < fixes_count; i++) free(fixes[i].fixed_value);
        fixes_count = 0;

        printf("\r  ✓ Applied %zu fixes                   \n", fixes_count ? fixes_count : (size_t)(total > 0 ? 1 : 0));
    }

    free(fixes);
    sqlite3_close(db);
    printf("Done!\n");
    return 0;
}
