import csv
import html
import mimetypes
import shutil
import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st


DOCUMENTS_CSV = Path("documents.csv")
FOLDERS_CSV = Path("folders.csv")
DATABASE_FILE = Path("hector.db")
DOCUMENT_FOLDER = Path("documents")
MISSING_FILE_MESSAGE = "Document file not found. Please check the file name and documents folder."

MAIN_CATEGORIES = ["IMS", "JDS", "JSA", "ORG Chart"]
DEFAULT_FOLDERS = {
    "IMS": [
        "ACCOUNTS",
        "ASSETS",
        "CONTRACTS",
        "FLOWS",
        "IMS",
        "MANAGEMENT",
        "OPERATIONS",
        "PAYROLL",
        "PERSONNEL",
        "PURCHASING",
        "QHSE",
        "QMS",
        "STORES",
        "WORKSHOP",
    ],
    "JDS": [
        "ACCOUNTS",
        "CONTRACTS",
        "EXECUTIVE MANAGEMENT",
        "GR",
        "HR",
        "MAINTENANCE",
        "MIS -IT",
        "OPERATIONS",
        "ORC",
        "QHSE",
        "SCM",
    ],
    "JSA": [],
    "ORG Chart": [],
}

DOCUMENT_COLUMNS = [
    "Document Name",
    "Code",
    "Department",
    "Keywords",
    "Related Documents",
    "File Name",
    "Category",
    "Subcategory",
]
FOLDER_COLUMNS = ["Category", "Subcategory"]
IMS_SYSTEM_FOLDERS = ["QMS", "EMS", "OHSMS"]
SEARCH_COLUMNS = ["Document Name", "Code", "Department", "Keywords"]
ALLOWED_UPLOAD_TYPES = ["pdf", "doc", "docx", "xls", "xlsx"]


def clean_folder_name(name):
    """Keep folder names readable and consistent."""
    return str(name).strip()


def safe_path_part(name):
    """Make a safe folder/file path part while keeping spaces readable."""
    cleaned = clean_folder_name(name)
    for character in ['<', '>', ':', '"', '/', "\\", "|", "?", "*"]:
        cleaned = cleaned.replace(character, "-")
    return cleaned or "Untitled"


def get_connection():
    """Open a SQLite connection with dictionary-like row access."""
    connection = sqlite3.connect(DATABASE_FILE)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def ensure_nested_folder_schema(connection):
    """Upgrade the folders table uniqueness rule for real nested folders."""
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'folders'"
    ).fetchone()
    if row is None or "UNIQUE(category_id, name)" not in str(row["sql"]):
        return

    connection.execute("PRAGMA foreign_keys = OFF")
    connection.execute(
        """
        CREATE TABLE folders_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category_id INTEGER NOT NULL,
            parent_folder_id INTEGER,
            UNIQUE(category_id, parent_folder_id, name),
            FOREIGN KEY(category_id) REFERENCES categories(id) ON DELETE CASCADE,
            FOREIGN KEY(parent_folder_id) REFERENCES folders_new(id) ON DELETE CASCADE
        )
        """
    )
    connection.execute(
        """
        INSERT INTO folders_new (id, name, category_id, parent_folder_id)
        SELECT id, name, category_id, parent_folder_id
        FROM folders
        """
    )
    connection.execute("DROP TABLE folders")
    connection.execute("ALTER TABLE folders_new RENAME TO folders")
    connection.execute("PRAGMA foreign_keys = ON")


def initialize_database():
    """Create Hector tables and seed default categories/folders safely."""
    DOCUMENT_FOLDER.mkdir(exist_ok=True)

    with get_connection() as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        # Categories are the top-level Hector menu items.
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE
            )
            """
        )
        # Folders are category subfolders. parent_folder_id is ready for future nesting.
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS folders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                category_id INTEGER NOT NULL,
                parent_folder_id INTEGER,
                UNIQUE(category_id, name),
                FOREIGN KEY(category_id) REFERENCES categories(id) ON DELETE CASCADE,
                FOREIGN KEY(parent_folder_id) REFERENCES folders(id) ON DELETE CASCADE
            )
            """
        )
        ensure_nested_folder_schema(connection)
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_folders_root_unique
            ON folders(category_id, name)
            WHERE parent_folder_id IS NULL
            """
        )
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_folders_child_unique
            ON folders(parent_folder_id, name)
            WHERE parent_folder_id IS NOT NULL
            """
        )
        # Documents store metadata and file paths only. Files remain in documents/.
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                code TEXT,
                department TEXT,
                keywords TEXT,
                file_name TEXT NOT NULL,
                file_path TEXT NOT NULL,
                category_id INTEGER NOT NULL,
                folder_id INTEGER,
                uploaded_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(name, file_name),
                FOREIGN KEY(category_id) REFERENCES categories(id) ON DELETE CASCADE,
                FOREIGN KEY(folder_id) REFERENCES folders(id) ON DELETE SET NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS document_relationships (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL,
                related_document_id INTEGER NOT NULL,
                UNIQUE(document_id, related_document_id),
                FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE,
                FOREIGN KEY(related_document_id) REFERENCES documents(id) ON DELETE CASCADE
            )
            """
        )

        seeded = connection.execute(
            "SELECT value FROM app_settings WHERE key = 'defaults_seeded'"
        ).fetchone()
        existing_categories = connection.execute("SELECT COUNT(*) AS count FROM categories").fetchone()["count"]

        if seeded is None and existing_categories == 0:
            for category in MAIN_CATEGORIES:
                connection.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", (category,))

            for category, folders in DEFAULT_FOLDERS.items():
                category_id = get_category_id(connection, category)
                for folder in folders:
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO folders (name, category_id, parent_folder_id)
                        VALUES (?, ?, NULL)
                        """,
                        (folder, category_id),
                    )

        connection.execute(
            """
            INSERT OR REPLACE INTO app_settings (key, value)
            VALUES ('defaults_seeded', 'true')
            """
        )
        ims_systems_seeded = connection.execute(
            "SELECT value FROM app_settings WHERE key = 'ims_systems_seeded'"
        ).fetchone()
        if ims_systems_seeded is None:
            ims_category_id = get_category_id(connection, "IMS")
            for folder in IMS_SYSTEM_FOLDERS:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO folders (name, category_id, parent_folder_id)
                    VALUES (?, ?, NULL)
                    """,
                    (folder, ims_category_id),
                )
            connection.execute(
                """
                INSERT OR REPLACE INTO app_settings (key, value)
                VALUES ('ims_systems_seeded', 'true')
                """
            )

    migrate_csv_to_sqlite()


def move_existing_root_documents():
    """Copy old prototype files into a demo/test area outside IMS."""
    documents = pd.read_csv(DOCUMENTS_CSV).fillna("")
    target_folder = DOCUMENT_FOLDER / "Demo" / "Sample Documents"
    target_folder.mkdir(parents=True, exist_ok=True)

    for _, document in documents.iterrows():
        file_name = str(document["File Name"]).strip()
        if not file_name:
            continue

        old_path = DOCUMENT_FOLDER / file_name
        new_path = target_folder / file_name

        if old_path.exists() and not new_path.exists():
            shutil.copy2(old_path, new_path)


def ensure_storage():
    """Compatibility wrapper used by the app startup."""
    try:
        initialize_database()
    except sqlite3.Error as error:
        st.error(f"Database error: {error}")
        st.stop()


def get_category_id(connection, category):
    """Return the id for a category, creating it if needed."""
    category = clean_folder_name(category)
    connection.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", (category,))
    row = connection.execute("SELECT id FROM categories WHERE name = ?", (category,)).fetchone()
    return row["id"]


def get_folder_id(connection, category, subcategory):
    """Return the id for a folder, creating it if needed."""
    category_id = get_category_id(connection, category)
    subcategory = clean_folder_name(subcategory)
    connection.execute(
        """
        INSERT OR IGNORE INTO folders (name, category_id, parent_folder_id)
        VALUES (?, ?, NULL)
        """,
        (subcategory, category_id),
    )
    row = connection.execute(
        "SELECT id FROM folders WHERE name = ? AND category_id = ?",
        (subcategory, category_id),
    ).fetchone()
    return row["id"]


def migrate_csv_to_sqlite():
    """Import existing CSV document records once, keeping CSV files as backup."""
    if not DOCUMENTS_CSV.exists():
        return

    with get_connection() as connection:
        migrated = connection.execute(
            "SELECT value FROM app_settings WHERE key = 'csv_migrated'"
        ).fetchone()
        existing_documents = connection.execute("SELECT COUNT(*) AS count FROM documents").fetchone()["count"]
        if migrated is not None:
            return
        if existing_documents > 0:
            connection.execute(
                "INSERT OR REPLACE INTO app_settings (key, value) VALUES ('csv_migrated', 'true')"
            )
            return

    with get_connection() as connection, DOCUMENTS_CSV.open(newline="", encoding="utf-8") as csv_file:
        for row in csv.DictReader(csv_file):
            document_name = clean_folder_name(row.get("Document Name", ""))
            file_name = clean_folder_name(row.get("File Name", ""))

            if not document_name or not file_name:
                continue

            duplicate = connection.execute(
                "SELECT id FROM documents WHERE name = ? AND file_name = ?",
                (document_name, file_name),
            ).fetchone()
            if duplicate:
                continue

            category = clean_folder_name(row.get("Category", "")) or "Demo"
            subcategory = clean_folder_name(row.get("Subcategory", "")) or "Sample Documents"
            category_id = get_category_id(connection, category)
            folder_id = get_folder_id(connection, category, subcategory)
            source_path = DOCUMENT_FOLDER / file_name
            target_path = folder_path(category, subcategory) / file_name
            target_path.parent.mkdir(parents=True, exist_ok=True)

            if source_path.exists() and not target_path.exists():
                shutil.copy2(source_path, target_path)

            connection.execute(
                """
                INSERT INTO documents (
                    name, code, department, keywords, file_name, file_path,
                    category_id, folder_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document_name,
                    clean_folder_name(row.get("Code", "")),
                    clean_folder_name(row.get("Department", "")),
                    clean_folder_name(row.get("Keywords", "")),
                    file_name,
                    str(target_path),
                    category_id,
                    folder_id,
                ),
            )
        connection.execute(
            "INSERT OR REPLACE INTO app_settings (key, value) VALUES ('csv_migrated', 'true')"
        )


def load_folders():
    """Load folder/category records from SQLite."""
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                folders.id,
                folders.parent_folder_id,
                categories.name AS Category,
                folders.name AS Subcategory
            FROM folders
            JOIN categories ON categories.id = folders.category_id
            ORDER BY categories.name, folders.parent_folder_id, folders.name
            """
        ).fetchall()
    return pd.DataFrame([dict(row) for row in rows], columns=["id", "parent_folder_id", *FOLDER_COLUMNS]).fillna("")


def load_categories():
    """Load main categories from SQLite so admin changes persist."""
    with get_connection() as connection:
        rows = connection.execute("SELECT id, name FROM categories ORDER BY name").fetchall()
    return pd.DataFrame([dict(row) for row in rows], columns=["id", "name"]).fillna("")


def get_category_name(category_id):
    """Return a category name by id."""
    with get_connection() as connection:
        row = connection.execute("SELECT name FROM categories WHERE id = ?", (category_id,)).fetchone()
    return "" if row is None else row["name"]


def get_folder_row(folder_id):
    """Return one folder row with its category name."""
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT
                folders.id,
                folders.name,
                folders.category_id,
                folders.parent_folder_id,
                categories.name AS category
            FROM folders
            JOIN categories ON categories.id = folders.category_id
            WHERE folders.id = ?
            """,
            (int(folder_id),),
        ).fetchone()


def get_child_folders(category_id, parent_folder_id=None):
    """Return folders directly under a category or parent folder."""
    with get_connection() as connection:
        if parent_folder_id is None:
            rows = connection.execute(
                """
                SELECT id, name, category_id, parent_folder_id
                FROM folders
                WHERE category_id = ? AND parent_folder_id IS NULL
                ORDER BY name
                """,
                (category_id,),
            ).fetchall()
        else:
            rows = connection.execute(
                """
                SELECT id, name, category_id, parent_folder_id
                FROM folders
                WHERE parent_folder_id = ?
                ORDER BY name
                """,
                (int(parent_folder_id),),
            ).fetchall()
    return rows


def get_folder_ancestors(folder_id):
    """Return folders from root to the selected folder."""
    folders = []
    current_id = int(folder_id) if folder_id else None
    with get_connection() as connection:
        while current_id:
            row = connection.execute(
                """
                SELECT id, name, category_id, parent_folder_id
                FROM folders
                WHERE id = ?
                """,
                (current_id,),
            ).fetchone()
            if row is None:
                break
            folders.append(row)
            current_id = row["parent_folder_id"]
    return list(reversed(folders))


def get_descendant_folder_ids(folder_id):
    """Return a folder id and all nested child folder ids."""
    folder_ids = [int(folder_id)]
    with get_connection() as connection:
        index = 0
        while index < len(folder_ids):
            rows = connection.execute(
                "SELECT id FROM folders WHERE parent_folder_id = ?",
                (folder_ids[index],),
            ).fetchall()
            folder_ids.extend(int(row["id"]) for row in rows)
            index += 1
    return folder_ids


def folder_storage_path(category, folder_id):
    """Build the physical storage path that mirrors the nested folder hierarchy."""
    path = DOCUMENT_FOLDER / safe_path_part(category)
    for folder in get_folder_ancestors(folder_id):
        path = path / safe_path_part(folder["name"])
    return path


def root_folder_id(category, folder_name):
    """Find a root folder id by category and name."""
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT folders.id
            FROM folders
            JOIN categories ON categories.id = folders.category_id
            WHERE categories.name = ? AND folders.name = ? AND folders.parent_folder_id IS NULL
            """,
            (category, folder_name),
        ).fetchone()
    return None if row is None else int(row["id"])


def save_folders(folders):
    """Compatibility helper retained for older calls."""
    return None


def load_documents():
    """Load document records from SQLite using the legacy display columns."""
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                documents.id,
                documents.name AS "Document Name",
                documents.code AS Code,
                documents.department AS Department,
                documents.keywords AS Keywords,
                '' AS "Related Documents",
                documents.file_name AS "File Name",
                documents.file_path AS "File Path",
                categories.name AS Category,
                documents.folder_id AS folder_id,
                folders.name AS Subcategory
            FROM documents
            JOIN categories ON categories.id = documents.category_id
            LEFT JOIN folders ON folders.id = documents.folder_id
            ORDER BY documents.name
            """
        ).fetchall()

    documents = pd.DataFrame([dict(row) for row in rows]).fillna("")
    if documents.empty:
        return pd.DataFrame(columns=["id", *DOCUMENT_COLUMNS, "File Path", "folder_id"]).set_index("id", drop=False)
    return documents.set_index("id", drop=False)


def save_documents(documents):
    """Delete-safe compatibility helper for bulk document updates."""
    with get_connection() as connection:
        existing_ids = set(
            row["id"] for row in connection.execute("SELECT id FROM documents").fetchall()
        )
        remaining_ids = set(int(row_id) for row_id in documents.index.tolist())
        for document_id in existing_ids - remaining_ids:
            connection.execute("DELETE FROM documents WHERE id = ?", (document_id,))


def documents_for_folder(documents, category, subcategory):
    """Return documents that belong to one folder/subcategory."""
    return documents[
        (documents["Category"].astype(str) == category)
        & (documents["Subcategory"].astype(str) == subcategory)
    ]


def documents_for_folder_id(documents, folder_id):
    """Return documents that belong to one folder id."""
    if documents.empty or "folder_id" not in documents.columns:
        return documents.iloc[0:0]
    return documents[documents["folder_id"].astype(str) == str(folder_id)]


def documents_for_folder_tree(documents, folder_id):
    """Return documents in a folder and all nested folders."""
    if documents.empty or "folder_id" not in documents.columns:
        return documents.iloc[0:0]
    folder_ids = [str(folder_id) for folder_id in get_descendant_folder_ids(folder_id)]
    return documents[documents["folder_id"].astype(str).isin(folder_ids)]


def documents_for_category(documents, category):
    """Return documents that belong to one main category."""
    return documents[documents["Category"].astype(str) == category]


def delete_physical_files(document_rows):
    """Delete document files from disk when the user explicitly asks for it."""
    for _, document in document_rows.iterrows():
        path = get_document_path(document)
        if path and path.exists():
            path.unlink()


def search_documents(documents, search_text):
    """Search document name, code, department, and keywords."""
    if not search_text:
        return documents

    search_text = search_text.lower()
    matches = documents[SEARCH_COLUMNS].apply(
        lambda row: row.astype(str)
        .str.lower()
        .str.contains(search_text, regex=False)
        .any(),
        axis=1,
    )
    return documents[matches]


def text_matches_query(text, query):
    """Return True when the query matches full text, partial text, or word starts."""
    text = str(text).lower()
    query = str(query).strip().lower()

    if not query:
        return False

    words = text.replace("-", " ").replace("/", " ").split()
    return query in text or any(word.startswith(query) for word in words)


def build_search_index():
    """Create one searchable list for categories, folders, and documents."""
    categories = load_categories()
    folders = load_folders()
    documents = load_documents()
    results = []

    for _, category_row in categories.iterrows():
        category = str(category_row["name"])
        results.append(
            {
                "Type": "Main Category",
                "Title": category,
                "Subtitle": "Main Hector category",
                "Search Text": category,
                "Category": category,
                "Subcategory": "",
                "Document Index": "",
            }
        )

    for _, folder in folders.iterrows():
        category = str(folder["Category"])
        subcategory = str(folder["Subcategory"])
        folder_id = int(folder["id"])
        folder_path_text = " ".join([ancestor["name"] for ancestor in get_folder_ancestors(folder_id)])
        results.append(
            {
                "Type": "Folder",
                "Title": subcategory,
                "Subtitle": f"{category} / {' / '.join([ancestor['name'] for ancestor in get_folder_ancestors(folder_id)])}",
                "Search Text": f"{category} {folder_path_text}",
                "Category": category,
                "Subcategory": subcategory,
                "Folder ID": folder_id,
                "Document Index": "",
            }
        )

    for document_index, document in documents.iterrows():
        title = str(document["Document Name"])
        category = str(document["Category"])
        subcategory = str(document["Subcategory"])
        folder_id = document.get("folder_id", "")
        folder_path_text = ""
        if str(folder_id).strip():
            folder_path_text = " ".join([folder["name"] for folder in get_folder_ancestors(int(folder_id))])
        results.append(
            {
                "Type": "Document",
                "Title": title,
                "Subtitle": f"{document['Code']} | {document['Department']} | {category} / {subcategory}",
                "Search Text": " ".join(
                    [
                        title,
                        str(document["Code"]),
                        str(document["Department"]),
                        str(document["Keywords"]),
                        category,
                        subcategory,
                        folder_path_text,
                    ]
                ),
                "Category": category,
                "Subcategory": subcategory,
                "Folder ID": folder_id,
                "Document Index": document_index,
            }
        )

    return results


def search_all(query):
    """Search categories, folders, and documents together."""
    if not query.strip():
        return []

    return [
        item
        for item in build_search_index()
        if text_matches_query(item["Search Text"], query)
    ]


def find_document(documents, value):
    """Find a document by code or document name."""
    value = str(value).strip().lower()
    match = documents[
        (documents["Code"].astype(str).str.lower() == value)
        | (documents["Document Name"].astype(str).str.lower() == value)
    ]
    return None if match.empty else match.iloc[0]


def folder_path(category, subcategory):
    """Build the local storage path for one folder."""
    return DOCUMENT_FOLDER / safe_path_part(category) / safe_path_part(subcategory)


def get_document_path(document):
    """Build the document file path from category, subcategory, and file name."""
    file_name = str(document["File Name"]).strip()
    if not file_name:
        return None

    file_path = str(document.get("File Path", "")).strip()
    if file_path and Path(file_path).exists():
        return Path(file_path)

    category = str(document.get("Category", "")).strip()
    subcategory = str(document.get("Subcategory", "")).strip()
    paths_to_try = []

    if category and subcategory:
        paths_to_try.append(folder_path(category, subcategory) / file_name)

    paths_to_try.append(DOCUMENT_FOLDER / file_name)

    for file_path in paths_to_try:
        if file_path.exists():
            return file_path

    return None


def insert_document_record(category, subcategory, metadata, folder_id=None):
    """Insert one uploaded document into SQLite using parameterized SQL."""
    with get_connection() as connection:
        category_id = get_category_id(connection, category)
        if folder_id is None:
            folder_id = get_folder_id(connection, category, subcategory)
        connection.execute(
            """
            INSERT OR IGNORE INTO documents (
                name, code, department, keywords, file_name, file_path,
                category_id, folder_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                metadata["Document Name"],
                metadata["Code"],
                metadata["Department"],
                metadata["Keywords"],
                metadata["File Name"],
                metadata["File Path"],
                category_id,
                folder_id,
            ),
        )


def apply_styles():
    """Add Hector 2.7 stable light theme styling."""
    st.markdown(
        """
        <style>
        :root {
            --hector-bg: #F5F7FA;
            --hector-card: #FFFFFF;
            --hector-primary: #1E3A8A;
            --hector-button: #2563EB;
            --hector-text: #111827;
            --hector-muted: #4B5563;
            --hector-border: #E5E7EB;
            --hector-danger: #B91C1C;
        }

        .stApp {
            background: var(--hector-bg);
            color: var(--hector-text);
        }
        [data-testid="stHeader"] {
            background: transparent;
        }
        .block-container {
            max-width: 1180px;
            padding-top: 2rem;
            padding-bottom: 3rem;
        }

        h1, h2, h3 {
            color: var(--hector-primary);
            font-weight: 800;
            letter-spacing: 0;
        }
        h1 { font-size: 2.5rem; }
        h2 { font-size: 1.75rem; margin-top: 1.5rem; }
        h3 { font-size: 1.25rem; }
        p, label {
            color: var(--hector-text);
            font-size: 1rem;
            line-height: 1.5;
        }

        .hector-header {
            background: var(--hector-primary);
            border-radius: 10px;
            padding: 30px;
            margin-bottom: 22px;
            box-shadow: 0 8px 22px rgba(30, 58, 138, 0.14);
        }
        .hector-header h1 {
            color: #FFFFFF;
            font-size: 2.75rem;
            line-height: 1.1;
            margin: 0;
        }
        .hector-header p {
            color: #FFFFFF;
            font-size: 1.1rem;
            margin: 8px 0 0 0;
        }

        .category-card,
        .subcategory-card,
        .document-card,
        .details-card,
        .placeholder-card,
        .search-result-card,
        .admin-card {
            background: var(--hector-card);
            border: 1px solid var(--hector-border);
            border-radius: 10px;
            padding: 18px;
            margin: 14px 0;
            box-shadow: 0 1px 3px rgba(17, 24, 39, 0.06);
        }
        .category-card,
        .subcategory-card,
        .search-result-card {
            min-height: 120px;
        }
        .category-card:hover,
        .subcategory-card:hover,
        .search-result-card:hover {
            border-color: var(--hector-button);
            box-shadow: 0 6px 16px rgba(37, 99, 235, 0.12);
        }
        .category-card h2,
        .subcategory-card h3,
        .document-card h3,
        .details-card h2 {
            color: var(--hector-primary);
            margin-top: 0;
        }
        .folder-icon {
            color: var(--hector-button);
            font-size: 1.3rem;
            font-weight: 800;
            margin-bottom: 8px;
        }
        .secondary-text,
        [data-testid="stCaptionContainer"] p {
            color: var(--hector-muted);
        }
        .missing-file {
            color: var(--hector-danger);
            font-weight: 700;
        }
        .result-type {
            display: inline-block;
            background: #EFF6FF;
            color: var(--hector-primary);
            border: 1px solid #BFDBFE;
            border-radius: 999px;
            padding: 3px 10px;
            font-size: 0.85rem;
            font-weight: 800;
            margin-bottom: 8px;
        }

        .breadcrumb-bar {
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            gap: 8px;
            margin: -6px 0 18px 0;
            color: var(--hector-muted);
        }
        .breadcrumb-current {
            color: var(--hector-text);
            font-weight: 800;
        }
        .breadcrumb-separator {
            color: var(--hector-muted);
        }
        .breadcrumb-spacer {
            padding-top: 0.45rem;
            color: var(--hector-muted);
            text-align: center;
        }

        div[data-testid="stTextInput"] input,
        div[data-testid="stTextArea"] textarea,
        div[data-baseweb="select"] > div {
            background-color: #FFFFFF;
            color: var(--hector-text);
            border-color: var(--hector-border);
            border-radius: 8px;
        }
        div[data-testid="stTextInput"] input::placeholder,
        div[data-testid="stTextArea"] textarea::placeholder {
            color: #6B7280;
        }
        div[data-testid="stTextInput"] input:focus,
        div[data-testid="stTextArea"] textarea:focus {
            border-color: var(--hector-button);
            box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.14);
        }
        div[data-baseweb="popover"],
        div[data-baseweb="menu"],
        ul[role="listbox"] {
            background-color: #FFFFFF;
            color: var(--hector-text);
            border: 1px solid var(--hector-border);
            border-radius: 8px;
        }
        li[role="option"],
        div[role="option"] {
            color: var(--hector-text);
            background-color: #FFFFFF;
        }
        li[role="option"]:hover,
        div[role="option"]:hover {
            background-color: #EFF6FF;
            color: var(--hector-primary);
        }

        div[data-testid="stFileUploader"] section {
            background-color: #FFFFFF;
            border-color: var(--hector-border);
            border-radius: 10px;
        }
        div[data-testid="stForm"] {
            background-color: #FFFFFF;
            border: 1px solid var(--hector-border);
            border-radius: 10px;
            padding: 18px;
            box-shadow: 0 1px 3px rgba(17, 24, 39, 0.06);
        }
        div[data-testid="stCheckbox"] label {
            color: var(--hector-text);
        }

        .stButton > button,
        .stDownloadButton > button,
        div[data-testid="stFormSubmitButton"] button {
            background-color: var(--hector-button);
            color: #FFFFFF;
            border: 1px solid var(--hector-button);
            border-radius: 8px;
            font-weight: 800;
            padding: 0.55rem 1rem;
        }
        .stButton > button:hover,
        .stDownloadButton > button:hover,
        div[data-testid="stFormSubmitButton"] button:hover {
            background-color: var(--hector-primary);
            border-color: var(--hector-primary);
            color: #FFFFFF;
        }
        .stButton > button p,
        .stDownloadButton > button p,
        div[data-testid="stFormSubmitButton"] button p {
            color: #FFFFFF;
            font-weight: 800;
        }
        button[kind="primary"] {
            background-color: var(--hector-danger);
            border-color: var(--hector-danger);
        }
        button[kind="primary"]:hover {
            background-color: #7F1D1D;
            border-color: #7F1D1D;
        }

        div[data-testid="stAlert"] {
            background-color: #FFFFFF;
            border: 1px solid var(--hector-border);
            border-radius: 8px;
            color: var(--hector-text);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def show_header(title, subtitle):
    """Show the main blue Hector header."""
    st.markdown(
        f"""
        <div class="hector-header">
            <h1>{html.escape(title)}</h1>
            <p>{html.escape(subtitle)}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def show_breadcrumbs(items):
    """Show clickable breadcrumb buttons for the current navigation path."""
    if not items:
        return

    st.markdown("<div class='breadcrumb-bar'>", unsafe_allow_html=True)
    columns = st.columns([1] * (len(items) * 2 - 1))

    for index, item in enumerate(items):
        column_index = index * 2
        with columns[column_index]:
            if index == len(items) - 1:
                st.markdown(
                    f"<span class='breadcrumb-current'>{html.escape(item['label'])}</span>",
                    unsafe_allow_html=True,
                )
            else:
                if st.button(item["label"], key=f"breadcrumb-{index}-{item['label']}"):
                    item["action"]()
                    st.rerun()

        if index < len(items) - 1:
            with columns[column_index + 1]:
                st.markdown("<div class='breadcrumb-spacer'>/</div>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)


def go_home():
    st.session_state.page = "Home"


def go_to_category(category):
    st.session_state.page = "Category"
    st.session_state.category = category


def go_to_folder(category, subcategory):
    st.session_state.page = "Folder"
    st.session_state.category = category
    st.session_state.subcategory = subcategory
    folder_id = root_folder_id(category, subcategory)
    if folder_id is not None:
        st.session_state.folder_id = folder_id


def go_to_folder_id(folder_id):
    folder = get_folder_row(folder_id)
    if folder is None:
        go_home()
        return
    st.session_state.page = "Folder"
    st.session_state.category = folder["category"]
    st.session_state.subcategory = folder["name"]
    st.session_state.folder_id = int(folder["id"])


def go_to_admin():
    st.session_state.page = "Admin"


def go_to_document(document_index):
    st.session_state.page = "Document"
    st.session_state.document_index = int(document_index)


def open_document_link(document):
    """Show an Open Document button or a missing-file message."""
    path = get_document_path(document)

    if path is None:
        st.markdown(f"<p class='missing-file'>{MISSING_FILE_MESSAGE}</p>", unsafe_allow_html=True)
        return

    mime_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
    resolved_path = path.resolve()

    st.download_button(
        label="Open / Download Document",
        data=path.read_bytes(),
        file_name=path.name,
        mime=mime_type,
    )
    st.caption(f"Debug file path: {resolved_path}")


def show_search_result(item, documents):
    """Show one global search result and its navigation button."""
    st.markdown(
        f"""
        <div class="search-result-card">
            <div class="result-type">{html.escape(item["Type"])}</div>
            <h3>{html.escape(item["Title"])}</h3>
            <p class="secondary-text">{html.escape(item["Subtitle"])}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if item["Type"] == "Main Category":
        if st.button(f"Open {item['Title']}", key=f"search-category-{item['Title']}"):
            go_to_category(item["Category"])
            st.rerun()
    elif item["Type"] == "Folder":
        button_label = f"Open {item['Title']}"
        if st.button(button_label, key=f"search-folder-{item['Folder ID']}"):
            go_to_folder_id(item["Folder ID"])
            st.rerun()
    else:
        document = documents.loc[int(item["Document Index"])]
        if st.button(f"View Document: {item['Title']}", key=f"search-doc-view-{item['Document Index']}"):
            go_to_document(item["Document Index"])
            st.rerun()
        open_document_link(document)


def show_home_page():
    """Show the Hector home page with global search, categories, and admin access."""
    show_header("Hector 2.7", "Search all documents, folders, and categories.")
    show_breadcrumbs([{"label": "Home", "action": go_home}])

    st.markdown("## Global Document Search")
    if "global_search_text" not in st.session_state:
        st.session_state.global_search_text = ""

    search_text = st.text_input(
        "Search across Hector",
        key="global_search_text",
        placeholder="Try assets, main, qhs, operations, document code, or keywords",
    )

    if search_text.strip():
        documents = load_documents()
        search_results = search_all(search_text)

        if not search_results:
            st.warning("No results found.")
        else:
            for item in search_results:
                show_search_result(item, documents)

    st.markdown("## Main Categories")
    all_categories = load_categories()["name"].astype(str).tolist()
    categories = ["IMS"] if "IMS" in all_categories else []

    if not categories:
        st.info("No main categories have been added yet. Use Admin / Manage Folders to add IMS.")
    else:
        for row_start in range(0, len(categories), 4):
            columns = st.columns(4)
            row_categories = categories[row_start : row_start + 4]

            for index, category in enumerate(row_categories):
                with columns[index]:
                    st.markdown(
                        f"""
                        <div class="category-card">
                            <h2>{html.escape(category)}</h2>
                            <p class="secondary-text">Open {html.escape(category)}</p>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                    if st.button(f"Open {category}", key=f"open-{category}"):
                        go_to_category(category)
                        st.rerun()

    st.markdown("## Admin")
    if st.button("Admin / Manage Folders"):
        go_to_admin()
        st.rerun()


def show_category_page(category):
    """Show subfolders for a main category."""
    categories = load_categories()["name"].astype(str).tolist()
    if category not in categories:
        st.warning("This category no longer exists. Returning to Home.")
        go_home()
        st.rerun()

    if st.button("Back to Home"):
        go_home()
        st.rerun()

    show_header(category, f"Choose a {category} folder.")
    show_breadcrumbs(
        [
            {"label": "Home", "action": go_home},
            {"label": category, "action": lambda: go_to_category(category)},
        ]
    )

    with get_connection() as connection:
        category_row = connection.execute("SELECT id FROM categories WHERE name = ?", (category,)).fetchone()
    if category_row is None:
        st.warning("This category no longer exists. Returning to Home.")
        go_home()
        st.rerun()

    root_folders = get_child_folders(category_row["id"], None)

    if not root_folders:
        st.info("No folders have been added yet. Use Admin / Manage Folders to add one.")
        return

    for row_start in range(0, len(root_folders), 4):
        columns = st.columns(4)
        row_subcategories = root_folders[row_start : row_start + 4]

        for index, folder in enumerate(row_subcategories):
            subcategory = folder["name"]
            with columns[index]:
                st.markdown(
                    f"""
                    <div class="subcategory-card">
                        <div class="folder-icon">Folder</div>
                        <h3>{html.escape(subcategory)}</h3>
                        <p class="secondary-text">Open {html.escape(subcategory)}</p>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                if st.button(f"Open {subcategory}", key=f"open-{category}-{subcategory}"):
                    go_to_folder_id(folder["id"])
                    st.rerun()


def show_upload_form(category, folder_id):
    """Allow users to upload documents into a selected folder."""
    st.markdown("### Upload Document")
    folder = get_folder_row(folder_id)
    if folder is None:
        st.error("Folder not found.")
        return
    subcategory = folder["name"]

    with st.form(f"upload-{category}-{folder_id}", clear_on_submit=True):
        uploaded_file = st.file_uploader(
            "Choose a PDF, Word, or Excel file",
            type=ALLOWED_UPLOAD_TYPES,
        )
        document_name = st.text_input("Document name")
        code = st.text_input("Document code")
        department = st.text_input("Department")
        keywords = st.text_input("Keywords")
        related_documents = st.text_input("Related documents")
        submitted = st.form_submit_button("Upload Document")

    if not submitted:
        return

    if uploaded_file is None:
        st.error("Please choose a file to upload.")
        return

    if not document_name.strip():
        st.error("Please enter a document name.")
        return

    target_folder = folder_storage_path(category, folder_id)
    target_folder.mkdir(parents=True, exist_ok=True)
    safe_file_name = safe_path_part(uploaded_file.name)
    target_path = target_folder / safe_file_name

    if target_path.exists():
        stem = target_path.stem
        suffix = target_path.suffix
        counter = 2
        while target_path.exists():
            target_path = target_folder / f"{stem} ({counter}){suffix}"
            counter += 1
        safe_file_name = target_path.name

    target_path.write_bytes(uploaded_file.getbuffer())

    new_document = {
        "Document Name": document_name.strip(),
        "Code": code.strip(),
        "Department": department.strip(),
        "Keywords": keywords.strip(),
        "Related Documents": related_documents.strip(),
        "File Name": safe_file_name,
        "File Path": str(target_path),
        "Category": category,
        "Subcategory": subcategory,
    }
    insert_document_record(category, subcategory, new_document, folder_id=folder_id)
    st.success("Document uploaded successfully.")


def show_document_card(document, key_prefix):
    """Show one document with metadata and an open button."""
    st.markdown(
        f"""
        <div class="document-card">
            <h3>{html.escape(str(document["Document Name"]))}</h3>
            <p class="secondary-text">{html.escape(str(document["Code"]))} | {html.escape(str(document["Department"]))}</p>
            <p><strong>Keywords:</strong> {html.escape(str(document["Keywords"]))}</p>
            <p><strong>File Name:</strong> {html.escape(str(document["File Name"]))}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    open_document_link(document)


def show_folder_documents(folder_id):
    """Show uploaded documents that belong to the current folder."""
    documents = load_documents()
    folder_documents = documents_for_folder_id(documents, folder_id)

    st.markdown("### Documents")

    if folder_documents.empty:
        st.info("No documents have been added to this folder yet.")
        return

    for index, document in folder_documents.iterrows():
        show_document_card(document, f"folder-{index}")


def show_create_subfolder_form(folder):
    """Create a child folder under the current folder."""
    st.markdown("### Create Subfolder")
    with st.form(f"create-subfolder-{folder['id']}", clear_on_submit=True):
        new_folder = st.text_input("Subfolder name")
        submitted = st.form_submit_button("Create Subfolder")

    if not submitted:
        return

    folder_name = clean_folder_name(new_folder)
    if not folder_name:
        st.error("Please enter a subfolder name.")
        return

    try:
        with get_connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO folders (name, category_id, parent_folder_id)
                VALUES (?, ?, ?)
                """,
                (folder_name, folder["category_id"], folder["id"]),
            )
            new_folder_id = cursor.lastrowid
        folder_storage_path(folder["category"], new_folder_id).mkdir(parents=True, exist_ok=True)
        st.success("Subfolder created.")
        st.rerun()
    except sqlite3.IntegrityError:
        st.warning("A folder with this name already exists here.")
    except sqlite3.Error as error:
        st.error(f"Database error: {error}")


def show_child_folders(folder):
    """Show and manage direct child folders."""
    child_folders = get_child_folders(folder["category_id"], folder["id"])
    st.markdown("### Subfolders")

    if not child_folders:
        st.info("No subfolders have been added yet.")
    else:
        for row_start in range(0, len(child_folders), 4):
            columns = st.columns(4)
            row_folders = child_folders[row_start : row_start + 4]
            for index, child in enumerate(row_folders):
                with columns[index]:
                    st.markdown(
                        f"""
                        <div class="subcategory-card">
                            <div class="folder-icon">Folder</div>
                            <h3>{html.escape(child["name"])}</h3>
                            <p class="secondary-text">Open folder</p>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                    if st.button(f"Open {child['name']}", key=f"open-child-{child['id']}"):
                        go_to_folder_id(child["id"])
                        st.rerun()

    if not child_folders:
        return

    st.markdown("### Delete Subfolder")
    child_options = {child["name"]: child for child in child_folders}
    selected_name = st.selectbox(
        "Subfolder to delete",
        list(child_options.keys()),
        key=f"delete-child-select-{folder['id']}",
    )
    selected_child = child_options[selected_name]

    documents = load_documents()
    selected_documents = documents_for_folder_tree(documents, selected_child["id"])
    selected_children = get_child_folders(selected_child["category_id"], selected_child["id"])
    if selected_documents.empty and not selected_children:
        st.info("This subfolder does not contain documents or subfolders.")
    else:
        st.warning("This subfolder contains folders/documents. Are you sure you want to delete it?")

    confirm_delete = st.checkbox(
        "I understand and want to delete this subfolder.",
        key=f"confirm-child-delete-{folder['id']}",
    )
    delete_files = st.checkbox(
        "Also delete physical document files in this subfolder.",
        key=f"delete-child-files-{folder['id']}",
    )

    if st.button("Delete Subfolder", type="primary", key=f"delete-child-button-{folder['id']}"):
        if not confirm_delete:
            st.error("Please confirm before deleting this subfolder.")
            return

        if delete_files:
            delete_physical_files(selected_documents)
            target_folder = folder_storage_path(folder["category"], selected_child["id"])
            if target_folder.exists():
                shutil.rmtree(target_folder)

        with get_connection() as connection:
            descendant_ids = get_descendant_folder_ids(selected_child["id"])
            placeholders = ",".join("?" for _ in descendant_ids)
            connection.execute(f"DELETE FROM documents WHERE folder_id IN ({placeholders})", descendant_ids)
            connection.execute("DELETE FROM folders WHERE id = ?", (selected_child["id"],))

        st.success("Subfolder deleted.")
        st.rerun()


def show_folder_page(folder_id):
    """Show one nested folder page with subfolders, upload, and document list."""
    folder = get_folder_row(folder_id)
    if folder is None:
        st.warning("This folder no longer exists. Returning to Home.")
        go_home()
        st.rerun()

    category = folder["category"]
    subcategory = folder["name"]
    ancestors = get_folder_ancestors(folder_id)

    if st.button(f"Back to {category}"):
        parent_id = folder["parent_folder_id"]
        if parent_id:
            go_to_folder_id(parent_id)
        else:
            go_to_category(category)
        st.rerun()

    show_header(subcategory, "Folders and documents.")
    breadcrumb_items = [
        {"label": "Home", "action": go_home},
        {"label": category, "action": lambda: go_to_category(category)},
    ]
    for ancestor in ancestors:
        ancestor_id = int(ancestor["id"])
        breadcrumb_items.append(
            {"label": ancestor["name"], "action": lambda folder_id=ancestor_id: go_to_folder_id(folder_id)}
        )
    show_breadcrumbs(breadcrumb_items)

    show_create_subfolder_form(folder)
    show_child_folders(folder)
    show_upload_form(category, folder_id)
    show_folder_documents(folder_id)


def show_related_documents(documents, document):
    """Show related documents as cards with open links and details buttons."""
    st.markdown("### Related Documents")
    related_text = str(document["Related Documents"])
    related_items = [item.strip() for item in related_text.split(",") if item.strip()]

    if not related_items:
        st.info("No related documents listed.")
        return

    for item in related_items:
        related_document = find_document(documents, item)
        if related_document is None:
            st.write(item)
            continue
        show_document_card(related_document, f"related-{item}")


def show_document_page(document_index):
    """Show a single document detail page with full breadcrumb navigation."""
    documents = load_documents()

    if document_index not in documents.index:
        show_header("Document Not Found", "The selected document could not be found.")
        show_breadcrumbs([{"label": "Home", "action": go_home}, {"label": "Document Not Found", "action": go_home}])
        return

    document = documents.loc[document_index]
    category = str(document["Category"])
    document_name = str(document["Document Name"])

    show_header(document_name, "Document details.")
    breadcrumb_items = [
        {"label": "Home", "action": go_home},
        {"label": category, "action": lambda: go_to_category(category)},
    ]
    folder_id = document.get("folder_id", "")
    if str(folder_id).strip():
        for folder in get_folder_ancestors(int(folder_id)):
            ancestor_id = int(folder["id"])
            breadcrumb_items.append(
                {"label": folder["name"], "action": lambda folder_id=ancestor_id: go_to_folder_id(folder_id)}
            )
    breadcrumb_items.append({"label": document_name, "action": lambda: go_to_document(document_index)})
    show_breadcrumbs(breadcrumb_items)
    show_document_details(documents, document)


def show_document_details(documents, document):
    """Show the selected document details."""
    st.markdown(
        f"""
        <div class="details-card">
            <h2>{html.escape(str(document["Document Name"]))}</h2>
            <p><strong>Code:</strong> {html.escape(str(document["Code"]))}</p>
            <p><strong>Department:</strong> {html.escape(str(document["Department"]))}</p>
            <p><strong>Keywords:</strong> {html.escape(str(document["Keywords"]))}</p>
            <p><strong>File Name:</strong> {html.escape(str(document["File Name"]))}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    open_document_link(document)
    show_related_documents(documents, document)


def show_admin_page():
    """Show admin tools for creating and deleting folders."""
    if st.button("Back to Home"):
        go_home()
        st.rerun()

    show_header("Admin / Manage Folders", "Create and delete Hector categories and folders.")
    show_breadcrumbs(
        [
            {"label": "Home", "action": go_home},
            {"label": "Admin / Manage Folders", "action": go_to_admin},
        ]
    )
    categories = load_categories()
    category_names = categories["name"].astype(str).tolist()
    folders = load_folders()
    documents = load_documents()

    st.markdown("## Manage Main Categories")
    st.markdown('<div class="admin-card">', unsafe_allow_html=True)
    with st.form("add-main-category", clear_on_submit=True):
        new_category = st.text_input("New main category name")
        add_category_submitted = st.form_submit_button("Add Main Category")

    if add_category_submitted:
        category_name = clean_folder_name(new_category)
        if not category_name:
            st.error("Please enter a main category name.")
        else:
            try:
                with get_connection() as connection:
                    connection.execute("INSERT INTO categories (name) VALUES (?)", (category_name,))
                st.success("Main category added.")
                st.rerun()
            except sqlite3.IntegrityError:
                st.warning("That main category already exists.")
            except sqlite3.Error as error:
                st.error(f"Database error: {error}")

    if category_names:
        selected_category_to_delete = st.selectbox(
            "Main category to delete",
            category_names,
            key="delete-main-category",
        )
        category_folders = folders[folders["Category"].astype(str) == selected_category_to_delete]
        category_documents = documents_for_category(documents, selected_category_to_delete)

        if category_folders.empty and category_documents.empty:
            st.info("This category does not contain folders or documents.")
        else:
            st.warning("This category contains folders/documents. Are you sure you want to delete it?")

        confirm_category_delete = st.checkbox(
            "I understand and want to delete this main category.",
            key="confirm-category-delete",
        )
        delete_category_files = st.checkbox(
            "Also delete physical document files in this category.",
            key="delete-category-files",
        )

        if st.button("Delete Main Category", type="primary"):
            if not confirm_category_delete:
                st.error("Please confirm before deleting this main category.")
            else:
                if delete_category_files:
                    delete_physical_files(category_documents)
                    target_category_folder = DOCUMENT_FOLDER / safe_path_part(selected_category_to_delete)
                    if target_category_folder.exists():
                        shutil.rmtree(target_category_folder)

                with get_connection() as connection:
                    connection.execute("DELETE FROM categories WHERE name = ?", (selected_category_to_delete,))

                if st.session_state.category == selected_category_to_delete:
                    go_home()
                st.success("Main category deleted.")
                st.rerun()
    else:
        st.info("There are no main categories to delete.")
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("## Add Folder")
    if not category_names:
        st.info("Add a main category before adding folders.")
        return

    with st.form("add-folder", clear_on_submit=True):
        category = st.selectbox("Main category", category_names)
        new_folder = st.text_input("New folder/subcategory name")
        submitted = st.form_submit_button("Add Folder")

    if submitted:
        folder_name = clean_folder_name(new_folder).upper()

        if not folder_name:
            st.error("Please enter a folder name.")
        else:
            try:
                with get_connection() as connection:
                    category_id = get_category_id(connection, category)
                    cursor = connection.execute(
                        """
                        INSERT INTO folders (name, category_id, parent_folder_id)
                        VALUES (?, ?, NULL)
                        """,
                        (folder_name, category_id),
                    )
                    new_folder_id = cursor.lastrowid
                folder_storage_path(category, new_folder_id).mkdir(parents=True, exist_ok=True)
                st.success("Folder added.")
                st.rerun()
            except sqlite3.IntegrityError:
                st.warning("That folder already exists.")
            except sqlite3.Error as error:
                st.error(f"Database error: {error}")

    st.markdown("## Delete Folder")
    if folders.empty:
        st.info("There are no folders to delete.")
        return

    folder_options = {}
    for _, row in folders.iterrows():
        folder_id = int(row["id"])
        path_parts = [ancestor["name"] for ancestor in get_folder_ancestors(folder_id)]
        label = f"{row['Category']} / {' / '.join(path_parts)}"
        folder_options[label] = folder_id

    selected_label = st.selectbox("Folder to delete", list(folder_options.keys()))
    selected_folder_id = folder_options[selected_label]
    selected_folder = get_folder_row(selected_folder_id)
    selected_category = selected_folder["category"]
    selected_subcategory = selected_folder["name"]
    selected_physical_folder = folder_storage_path(selected_category, selected_folder_id)
    folder_documents = documents_for_folder_tree(documents, selected_folder_id)

    if folder_documents.empty:
        st.info("This folder does not contain documents.")
    else:
        st.warning("This folder contains documents. Are you sure you want to delete it?")

    confirm = st.checkbox("I understand and want to delete this folder.")
    delete_files = st.checkbox("Also delete document records and files in this folder.")

    if st.button("Delete Folder", type="primary"):
        if not confirm:
            st.error("Please confirm before deleting this folder.")
            return

        if not folder_documents.empty and not delete_files:
            st.error("This folder contains documents. Confirm document deletion or move them first.")
            return

        with get_connection() as connection:
            descendant_ids = get_descendant_folder_ids(selected_folder_id)
            placeholders = ",".join("?" for _ in descendant_ids)
            connection.execute(f"DELETE FROM documents WHERE folder_id IN ({placeholders})", descendant_ids)
            connection.execute("DELETE FROM folders WHERE id = ?", (selected_folder_id,))

        if delete_files:
            if selected_physical_folder.exists():
                shutil.rmtree(selected_physical_folder)

        st.success("Folder deleted.")
        st.rerun()


def main():
    st.set_page_config(page_title="Hector 2.7", layout="wide")
    ensure_storage()
    apply_styles()

    if "page" not in st.session_state:
        st.session_state.page = "Home"
    if "category" not in st.session_state:
        st.session_state.category = ""
    if "subcategory" not in st.session_state:
        st.session_state.subcategory = ""
    if "folder_id" not in st.session_state:
        st.session_state.folder_id = 0
    if "document_index" not in st.session_state:
        st.session_state.document_index = 0

    if st.session_state.page == "Home":
        show_home_page()
    elif st.session_state.page == "Category":
        show_category_page(st.session_state.category)
    elif st.session_state.page == "Folder":
        show_folder_page(st.session_state.folder_id)
    elif st.session_state.page == "Admin":
        show_admin_page()
    elif st.session_state.page == "Document":
        show_document_page(st.session_state.document_index)


if __name__ == "__main__":
    main()
