app_name = "velora_search"
app_title = "Global search"
app_description = "Find any document from one box: full-text, prefix and typo-tolerant (PostgreSQL), accent-insensitive, permission-aware"
required_apps = []
required_velora = ">=0.8"
required_packages = []
after_install = "velora_search.indexer.reindex_all"
before_uninstall = None

doc_events = {"*": {"after_insert": "velora_search.indexer.on_save", "on_update": "velora_search.indexer.on_save", "on_submit": "velora_search.indexer.on_save",
                    "on_cancel": "velora_search.indexer.on_remove", "after_delete": "velora_search.indexer.on_remove"}}

# PostgreSQL: a generated tsvector with a GIN index (full-text, prefix) and a trigram index on the title (typo tolerance: "Acmee" finds "Acme").
pg_objects = [
    {"name": "search_index_fulltext",
     "description": "Full-text search over title and text, computed by the database and indexed with GIN.",
     "sql": ["ALTER TABLE tab_search_index ADD COLUMN IF NOT EXISTS tsv tsvector GENERATED ALWAYS AS (to_tsvector('simple', coalesce(title_norm, '') || ' ' || coalesce(body_norm, ''))) STORED",
             "CREATE INDEX IF NOT EXISTS gin_search_index_tsv ON tab_search_index USING gin (tsv)",
             "CREATE UNIQUE INDEX IF NOT EXISTS uq_search_index_doc ON tab_search_index (ref_doctype, ref_name)"]},
    {"name": "search_index_trigram",
     "description": "Typo-tolerant matching of titles (pg_trgm).",
     "requires": ["pg_trgm"],
     "sql": ["CREATE INDEX IF NOT EXISTS gin_search_index_title_trgm ON tab_search_index USING gin (title_norm gin_trgm_ops)"]},
]
