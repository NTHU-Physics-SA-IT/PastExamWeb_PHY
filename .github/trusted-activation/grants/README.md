# Grants

Each activation grant is one immutable, UUID-named JSON file validated against
the grant schema. Existing grant files are never edited or deleted. A grant
becomes authority only after its main-target pull request merges and its exact
protected-main commit is Green.
