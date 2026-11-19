-- Document frequency for the coverage gate.
--
-- The gate weights matched query terms by how rare they are; a term in one chunk
-- says far more about a passage than a term in fifteen hundred. Counting is
-- cached here so each term is measured once rather than on every query.

CREATE TABLE IF NOT EXISTS corpus_term_df (
    term text PRIMARY KEY,
    df integer NOT NULL,
    computed_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS corpus_term_df_df_idx ON corpus_term_df (df);

GRANT SELECT, INSERT, UPDATE ON corpus_term_df TO search_mcp;
GRANT SELECT, INSERT, UPDATE ON corpus_term_df TO explore_mcp;
