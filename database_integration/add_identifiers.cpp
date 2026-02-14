/*
 * Add identifiers to SQLite database from JSON file.
 *
 * Creates two tables:
 * 1. identifier_types (property_id, name_en) - reference table for property names
 * 2. identifiers (wikidata_id, property_id, value) - the actual identifier values
 *
 * Streams through the JSON to handle large files (1GB+).
 *
 * Compile: g++ -O3 -std=c++17 -o add_identifiers add_identifiers.cpp -lsqlite3
 * Run: ./add_identifiers ../data/humans_clean.sqlite3 ../data/all_humans/all_human_identifiers.json
 */

#include <iostream>
#include <fstream>
#include <string>
#include <unordered_set>
#include <unordered_map>
#include <vector>
#include <cstring>
#include <ctime>
#include <sqlite3.h>

constexpr size_t BATCH_SIZE = 50000;
constexpr size_t BUFFER_SIZE = 64 * 1024 * 1024;  // 64MB read buffer
constexpr size_t PROGRESS_INTERVAL = 100000;

// Skip whitespace
inline void skip_whitespace(const char*& p, const char* end) {
    while (p < end && (*p == ' ' || *p == '\n' || *p == '\r' || *p == '\t')) p++;
}

// Parse a JSON string (assumes p points to opening quote)
inline bool parse_string(const char*& p, const char* end, std::string& out) {
    if (p >= end || *p != '"') return false;
    p++;  // skip opening quote

    out.clear();
    while (p < end && *p != '"') {
        if (*p == '\\' && p + 1 < end) {
            p++;
            switch (*p) {
                case '"': out += '"'; break;
                case '\\': out += '\\'; break;
                case 'n': out += '\n'; break;
                case 'r': out += '\r'; break;
                case 't': out += '\t'; break;
                case '/': out += '/'; break;
                default: out += *p; break;
            }
        } else {
            out += *p;
        }
        p++;
    }
    if (p < end && *p == '"') {
        p++;  // skip closing quote
        return true;
    }
    return false;
}

int main(int argc, char* argv[]) {
    if (argc != 3) {
        std::cerr << "Usage: " << argv[0] << " <database.sqlite3> <identifiers.json>\n";
        return 1;
    }

    const char* db_path = argv[1];
    const char* json_path = argv[2];

    std::cout << "============================================================\n";
    std::cout << "ADD IDENTIFIERS TO DATABASE\n";
    std::cout << "============================================================\n\n";
    std::cout.flush();

    // Open database
    std::cout << "[1/5] Opening database...\n";
    std::cout.flush();

    sqlite3* db;
    int rc = sqlite3_open(db_path, &db);
    if (rc != SQLITE_OK) {
        std::cerr << "Cannot open database: " << sqlite3_errmsg(db) << "\n";
        return 1;
    }
    std::cout << "  Opened " << db_path << "\n";

    // Optimize for speed
    sqlite3_exec(db, "PRAGMA synchronous = OFF", nullptr, nullptr, nullptr);
    sqlite3_exec(db, "PRAGMA journal_mode = MEMORY", nullptr, nullptr, nullptr);
    sqlite3_exec(db, "PRAGMA cache_size = 1000000", nullptr, nullptr, nullptr);

    // Create tables
    std::cout << "\n[2/5] Creating tables...\n";
    std::cout.flush();

    const char* create_sql = R"(
        DROP TABLE IF EXISTS identifiers;
        DROP TABLE IF EXISTS identifier_types;

        CREATE TABLE identifier_types (
            property_id TEXT PRIMARY KEY,
            name_en TEXT
        );

        CREATE TABLE identifiers (
            wikidata_id TEXT,
            property_id TEXT,
            value TEXT,
            PRIMARY KEY (wikidata_id, property_id, value)
        );
    )";

    char* err_msg = nullptr;
    rc = sqlite3_exec(db, create_sql, nullptr, nullptr, &err_msg);
    if (rc != SQLITE_OK) {
        std::cerr << "Cannot create tables: " << err_msg << "\n";
        sqlite3_free(err_msg);
        return 1;
    }
    std::cout << "  Tables created.\n";

    // Open JSON file
    std::cout << "\n[3/5] Reading identifiers JSON (streaming)...\n";
    std::cout.flush();

    std::ifstream file(json_path, std::ios::binary);
    if (!file) {
        std::cerr << "Cannot open JSON file: " << json_path << "\n";
        return 1;
    }

    // Get file size
    file.seekg(0, std::ios::end);
    size_t file_size = file.tellg();
    file.seekg(0, std::ios::beg);
    std::cout << "  File size: " << (file_size / (1024 * 1024)) << " MB\n";

    // Prepare insert statement
    sqlite3_stmt* stmt_insert;
    rc = sqlite3_prepare_v2(db, "INSERT OR IGNORE INTO identifiers (wikidata_id, property_id, value) VALUES (?, ?, ?)",
                            -1, &stmt_insert, nullptr);
    if (rc != SQLITE_OK) {
        std::cerr << "Cannot prepare insert: " << sqlite3_errmsg(db) << "\n";
        return 1;
    }

    // Allocate buffer
    std::vector<char> buffer(BUFFER_SIZE + 1);
    std::string leftover;
    std::unordered_set<std::string> property_ids;

    size_t total_rows = 0;
    size_t total_individuals = 0;
    size_t bytes_read = 0;
    clock_t start = clock();

    sqlite3_exec(db, "BEGIN TRANSACTION", nullptr, nullptr, nullptr);

    // State machine for parsing
    enum State { EXPECT_OPEN, EXPECT_QID_OR_CLOSE, EXPECT_COLON, EXPECT_PROPS, IN_PROPS };
    State state = EXPECT_OPEN;
    std::string current_qid;
    std::string current_prop;
    bool in_array = false;

    while (file) {
        // Read chunk
        file.read(buffer.data(), BUFFER_SIZE);
        size_t chunk_size = file.gcount();
        bytes_read += chunk_size;

        // Combine with leftover
        std::string data = leftover + std::string(buffer.data(), chunk_size);
        leftover.clear();

        const char* p = data.c_str();
        const char* end = p + data.size();

        while (p < end) {
            skip_whitespace(p, end);
            if (p >= end) break;

            switch (state) {
                case EXPECT_OPEN:
                    if (*p == '{') {
                        p++;
                        state = EXPECT_QID_OR_CLOSE;
                    } else {
                        p++;
                    }
                    break;

                case EXPECT_QID_OR_CLOSE:
                    skip_whitespace(p, end);
                    if (p >= end) break;

                    if (*p == '}') {
                        p++;
                        state = EXPECT_OPEN;  // Done
                    } else if (*p == '"') {
                        // Check if we have complete string
                        const char* str_start = p;
                        p++;
                        while (p < end && *p != '"') {
                            if (*p == '\\' && p + 1 < end) p++;
                            p++;
                        }
                        if (p >= end) {
                            // Incomplete string, save and continue
                            leftover = std::string(str_start, end - str_start);
                            p = end;
                            break;
                        }
                        p++;  // skip closing quote

                        // Extract QID
                        current_qid = std::string(str_start + 1, p - str_start - 2);
                        state = EXPECT_COLON;
                        total_individuals++;
                    } else if (*p == ',') {
                        p++;
                    } else {
                        p++;
                    }
                    break;

                case EXPECT_COLON:
                    skip_whitespace(p, end);
                    if (p >= end) break;

                    if (*p == ':') {
                        p++;
                        state = EXPECT_PROPS;
                    } else {
                        p++;
                    }
                    break;

                case EXPECT_PROPS:
                    skip_whitespace(p, end);
                    if (p >= end) break;

                    if (*p == '{') {
                        p++;
                        state = IN_PROPS;
                    } else {
                        p++;
                    }
                    break;

                case IN_PROPS:
                    skip_whitespace(p, end);
                    if (p >= end) break;

                    if (*p == '}') {
                        p++;
                        state = EXPECT_QID_OR_CLOSE;
                    } else if (*p == '"') {
                        // Property ID
                        std::string prop_id;
                        if (!parse_string(p, end, prop_id)) {
                            // Incomplete, save leftover
                            leftover = std::string(p, end - p);
                            p = end;
                            break;
                        }
                        current_prop = prop_id;
                        property_ids.insert(prop_id);

                        // Expect colon
                        skip_whitespace(p, end);
                        if (p >= end || *p != ':') {
                            if (p >= end) {
                                leftover = "\"" + prop_id + "\"";
                                break;
                            }
                            p++;
                            continue;
                        }
                        p++;  // skip colon

                        skip_whitespace(p, end);
                        if (p >= end) {
                            leftover = "\"" + prop_id + "\":";
                            break;
                        }

                        // Value: string or array
                        if (*p == '"') {
                            std::string value;
                            if (!parse_string(p, end, value)) {
                                leftover = std::string(p - prop_id.length() - 4, end - (p - prop_id.length() - 4));
                                p = end;
                                break;
                            }

                            // Insert
                            sqlite3_bind_text(stmt_insert, 1, current_qid.c_str(), -1, SQLITE_TRANSIENT);
                            sqlite3_bind_text(stmt_insert, 2, current_prop.c_str(), -1, SQLITE_TRANSIENT);
                            sqlite3_bind_text(stmt_insert, 3, value.c_str(), -1, SQLITE_TRANSIENT);
                            sqlite3_step(stmt_insert);
                            sqlite3_reset(stmt_insert);
                            total_rows++;

                        } else if (*p == '[') {
                            p++;  // skip [

                            while (p < end) {
                                skip_whitespace(p, end);
                                if (p >= end) break;

                                if (*p == ']') {
                                    p++;
                                    break;
                                } else if (*p == '"') {
                                    std::string value;
                                    if (!parse_string(p, end, value)) {
                                        // Incomplete array - this is tricky, reset
                                        break;
                                    }

                                    // Insert
                                    sqlite3_bind_text(stmt_insert, 1, current_qid.c_str(), -1, SQLITE_TRANSIENT);
                                    sqlite3_bind_text(stmt_insert, 2, current_prop.c_str(), -1, SQLITE_TRANSIENT);
                                    sqlite3_bind_text(stmt_insert, 3, value.c_str(), -1, SQLITE_TRANSIENT);
                                    sqlite3_step(stmt_insert);
                                    sqlite3_reset(stmt_insert);
                                    total_rows++;

                                } else if (*p == ',') {
                                    p++;
                                } else {
                                    p++;
                                }
                            }
                        } else {
                            p++;
                        }

                    } else if (*p == ',') {
                        p++;
                    } else {
                        p++;
                    }
                    break;
            }

            // Progress
            if (total_rows % PROGRESS_INTERVAL == 0 && total_rows > 0) {
                double pct = 100.0 * bytes_read / file_size;
                std::cout << "\r  Progress: " << total_rows << " identifiers, "
                          << total_individuals << " individuals (" << (int)pct << "%)...";
                std::cout.flush();
            }

            // Batch commit
            if (total_rows % BATCH_SIZE == 0 && total_rows > 0) {
                sqlite3_exec(db, "COMMIT", nullptr, nullptr, nullptr);
                sqlite3_exec(db, "BEGIN TRANSACTION", nullptr, nullptr, nullptr);
            }
        }
    }

    sqlite3_exec(db, "COMMIT", nullptr, nullptr, nullptr);
    sqlite3_finalize(stmt_insert);
    file.close();

    double elapsed = (double)(clock() - start) / CLOCKS_PER_SEC;
    std::cout << "\n  Inserted " << total_rows << " identifier rows for "
              << total_individuals << " individuals in " << (int)elapsed << "s\n";
    std::cout << "  Found " << property_ids.size() << " unique property types\n";

    // Insert property types (without labels - can be fetched later)
    std::cout << "\n[4/5] Populating identifier_types table...\n";
    std::cout.flush();

    sqlite3_stmt* stmt_prop;
    rc = sqlite3_prepare_v2(db, "INSERT INTO identifier_types (property_id, name_en) VALUES (?, NULL)",
                            -1, &stmt_prop, nullptr);

    sqlite3_exec(db, "BEGIN TRANSACTION", nullptr, nullptr, nullptr);
    for (const auto& pid : property_ids) {
        sqlite3_bind_text(stmt_prop, 1, pid.c_str(), -1, SQLITE_TRANSIENT);
        sqlite3_step(stmt_prop);
        sqlite3_reset(stmt_prop);
    }
    sqlite3_exec(db, "COMMIT", nullptr, nullptr, nullptr);
    sqlite3_finalize(stmt_prop);

    std::cout << "  Inserted " << property_ids.size() << " identifier types (labels can be fetched later)\n";

    // Create indexes
    std::cout << "\n[5/5] Creating indexes...\n";
    std::cout.flush();
    start = clock();

    sqlite3_exec(db, "CREATE INDEX IF NOT EXISTS idx_identifiers_qid ON identifiers(wikidata_id)", nullptr, nullptr, nullptr);
    sqlite3_exec(db, "CREATE INDEX IF NOT EXISTS idx_identifiers_prop ON identifiers(property_id)", nullptr, nullptr, nullptr);

    elapsed = (double)(clock() - start) / CLOCKS_PER_SEC;
    std::cout << "  Indexes created in " << (int)elapsed << "s\n";

    sqlite3_close(db);

    std::cout << "\n============================================================\n";
    std::cout << "DONE!\n";
    std::cout << "============================================================\n";

    return 0;
}
