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


def initialize_database():
    """Create Hector tables and seed default categories/folders safely."""
    DOCUMENT_FOLDER.mkdir(exist_ok=True)

    with get_connection() as connection:
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


def load_folders():
    """Load folder/category records from SQLite."""
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT folders.id, categories.name AS Category, folders.name AS Subcategory
            FROM folders
            JOIN categories ON categories.id = folders.category_id
            ORDER BY categories.name, folders.name
            """
        ).fetchall()
    return pd.DataFrame([dict(row) for row in rows], columns=["id", *FOLDER_COLUMNS]).fillna("")


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
                folders.name AS Subcategory
            FROM documents
            JOIN categories ON categories.id = documents.category_id
            LEFT JOIN folders ON folders.id = documents.folder_id
            ORDER BY documents.name
            """
        ).fetchall()

    documents = pd.DataFrame([dict(row) for row in rows]).fillna("")
    if documents.empty:
        return pd.DataFrame(columns=["id", *DOCUMENT_COLUMNS, "File Path"]).set_index("id", drop=False)
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
    folders = load_folders()
    documents = load_documents()
    results = []

    for category in MAIN_CATEGORIES:
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
        results.append(
            {
                "Type": "Folder/Subcategory",
                "Title": subcategory,
                "Subtitle": f"{category} folder",
                "Search Text": f"{category} {subcategory}",
                "Category": category,
                "Subcategory": subcategory,
                "Document Index": "",
            }
        )

    for document_index, document in documents.iterrows():
        title = str(document["Document Name"])
        category = str(document["Category"])
        subcategory = str(document["Subcategory"])
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
                    ]
                ),
                "Category": category,
                "Subcategory": subcategory,
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


def insert_document_record(category, subcategory, metadata):
    """Insert one uploaded document into SQLite using parameterized SQL."""
    with get_connection() as connection:
        category_id = get_category_id(connection, category)
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
    """Add Hector 2.3 full light theme restoration styling."""
    st.markdown(
        """
        <style>
        :root {
            --hector-bg: #F5F7FA;
            --hector-card: #FFFFFF;
            --hector-primary: #1E3A8A;
            --hector-action: #2563EB;
            --hector-text: #111827;
            --hector-secondary: #4B5563;
            --hector-border: #E5E7EB;
            --hector-danger: #B91C1C;
        }

        html, body, .stApp, [data-testid="stAppViewContainer"], [data-testid="stSidebar"] {
            background: var(--hector-bg) !important;
            color: var(--hector-text) !important;
            font-family: Arial, sans-serif !important;
        }
        [data-testid="stHeader"], header {
            background: rgba(245, 247, 250, 0) !important;
        }
        .block-container {
            max-width: 1180px;
            padding-top: 32px;
            padding-bottom: 48px;
        }

        h1, h2, h3, h4, h5, h6 {
            color: var(--hector-primary) !important;
            letter-spacing: 0 !important;
            font-weight: 800 !important;
        }
        h1 { font-size: 42px !important; }
        h2 { font-size: 28px !important; margin-top: 24px !important; }
        h3 { font-size: 22px !important; }
        p, label, span, div, li {
            color: var(--hector-text);
            font-size: 17px;
            line-height: 1.5;
        }
        label, [data-testid="stWidgetLabel"] p {
            color: var(--hector-text) !important;
            font-size: 16px !important;
            font-weight: 700 !important;
        }

        .hector-header {
            background: var(--hector-primary);
            color: #FFFFFF;
            padding: 30px;
            border-radius: 10px;
            margin-bottom: 24px;
            box-shadow: 0 8px 22px rgba(30, 58, 138, 0.16);
        }
        .hector-header h1 {
            color: #FFFFFF !important;
            margin: 0 !important;
            font-size: 44px !important;
            line-height: 1.1 !important;
        }
        .hector-header p {
            color: #FFFFFF !important;
            margin: 8px 0 0 0 !important;
            font-size: 18px !important;
        }

        .document-card, .details-card, .category-card, .subcategory-card,
        .placeholder-card, .search-result-card, [data-testid="stForm"] {
            background: var(--hector-card) !important;
            border: 1px solid var(--hector-border) !important;
            border-radius: 10px !important;
            padding: 18px !important;
            margin: 14px 0 !important;
            box-shadow: 0 1px 3px rgba(17, 24, 39, 0.06) !important;
        }
        .category-card, .subcategory-card, .search-result-card {
            min-height: 130px;
            cursor: pointer;
        }
        .search-result-card { min-height: 95px; }
        .category-card:hover, .subcategory-card:hover, .search-result-card:hover {
            border-color: var(--hector-action) !important;
            box-shadow: 0 6px 18px rgba(37, 99, 235, 0.16) !important;
        }
        .category-card h2, .subcategory-card h3, .details-card h2, .document-card h3 {
            color: var(--hector-primary) !important;
        }
        .folder-icon { color: var(--hector-action); font-size: 30px; margin-bottom: 8px; }
        .secondary-text, .stCaption, [data-testid="stCaptionContainer"],
        [data-testid="stCaptionContainer"] p {
            color: var(--hector-secondary) !important;
        }
        .missing-file {
            color: var(--hector-danger) !important;
            font-weight: 700;
            margin-top: 8px;
        }
        .breadcrumbs {
            margin: -8px 0 18px 0;
            color: var(--hector-secondary) !important;
            font-size: 16px;
        }
        .breadcrumb-current {
            color: var(--hector-text) !important;
            font-weight: 700;
        }
        .result-type {
            display: inline-block;
            background: #EFF6FF;
            color: var(--hector-primary) !important;
            border: 1px solid #BFDBFE;
            border-radius: 999px;
            padding: 3px 10px;
            font-size: 14px;
            font-weight: 700;
            margin-bottom: 8px;
        }

        input, textarea, select, option,
        div[data-testid="stTextInput"] input,
        div[data-testid="stTextArea"] textarea,
        div[data-testid="stNumberInput"] input,
        div[data-baseweb="input"] input,
        div[data-baseweb="textarea"] textarea {
            background: var(--hector-card) !important;
            color: var(--hector-text) !important;
            border-color: var(--hector-border) !important;
            caret-color: var(--hector-text) !important;
            font-size: 17px !important;
        }
        input::placeholder, textarea::placeholder {
            color: #6B7280 !important;
            opacity: 1 !important;
        }
        input:focus, textarea:focus,
        div[data-testid="stTextInput"] input:focus,
        div[data-testid="stTextArea"] textarea:focus {
            border-color: var(--hector-action) !important;
            box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.16) !important;
            outline: none !important;
        }

        div[data-testid="stSelectbox"],
        div[data-baseweb="select"],
        div[data-baseweb="select"] > div,
        div[data-baseweb="select"] div,
        div[data-baseweb="select"] input {
            background: var(--hector-card) !important;
            color: var(--hector-text) !important;
            border-color: var(--hector-border) !important;
        }
        div[data-baseweb="select"] svg {
            fill: var(--hector-secondary) !important;
            color: var(--hector-secondary) !important;
        }
        [data-baseweb="popover"], [data-baseweb="popover"] *,
        [data-baseweb="menu"], [data-baseweb="menu"] *,
        ul[role="listbox"], ul[role="listbox"] *,
        div[role="listbox"], div[role="listbox"] *,
        li[role="option"], div[role="option"] {
            background: var(--hector-card) !important;
            color: var(--hector-text) !important;
            border-color: var(--hector-border) !important;
        }
        li[role="option"]:hover, div[role="option"]:hover,
        li[aria-selected="true"], div[aria-selected="true"] {
            background: #EFF6FF !important;
            color: var(--hector-primary) !important;
        }

        [data-testid="stFileUploader"] section,
        [data-testid="stFileUploader"] section *,
        [data-testid="stFileUploaderDropzone"],
        [data-testid="stFileUploaderDropzone"] * {
            background: var(--hector-card) !important;
            color: var(--hector-text) !important;
            border-color: var(--hector-border) !important;
        }
        [data-testid="stFileUploader"] small,
        [data-testid="stFileUploader"] span {
            color: var(--hector-secondary) !important;
        }

        [data-testid="stCheckbox"], [data-testid="stCheckbox"] *,
        [data-testid="stCheckbox"] label, [data-testid="stCheckbox"] p {
            color: var(--hector-text) !important;
            background: transparent !important;
        }
        [data-testid="stCheckbox"] [data-testid="stMarkdownContainer"] p {
            font-weight: 600 !important;
        }

        .stButton > button,
        .stDownloadButton > button,
        button[kind="secondary"],
        div[data-testid="stFormSubmitButton"] button,
        [data-testid="stFileUploader"] button {
            background: var(--hector-action) !important;
            color: #FFFFFF !important;
            border: 1px solid var(--hector-action) !important;
            border-radius: 8px !important;
            padding: 10px 16px !important;
            font-size: 16px !important;
            font-weight: 700 !important;
            box-shadow: none !important;
            cursor: pointer !important;
        }
        .stButton > button:hover,
        .stDownloadButton > button:hover,
        button[kind="secondary"]:hover,
        div[data-testid="stFormSubmitButton"] button:hover,
        [data-testid="stFileUploader"] button:hover {
            background: var(--hector-primary) !important;
            border-color: var(--hector-primary) !important;
            color: #FFFFFF !important;
        }
        .stButton > button *,
        .stDownloadButton > button *,
        div[data-testid="stFormSubmitButton"] button *,
        [data-testid="stFileUploader"] button * {
            color: #FFFFFF !important;
            font-size: 16px !important;
            font-weight: 700 !important;
        }
        button[kind="primary"] {
            background: var(--hector-danger) !important;
            color: #FFFFFF !important;
            border: 1px solid var(--hector-danger) !important;
            border-radius: 8px !important;
            padding: 10px 16px !important;
            font-size: 16px !important;
            font-weight: 800 !important;
        }
        button[kind="primary"]:hover {
            background: #7F1D1D !important;
            border-color: #7F1D1D !important;
            color: #FFFFFF !important;
        }
        button[kind="primary"] * {
            color: #FFFFFF !important;
            font-weight: 800 !important;
        }

        .stAlert, [data-testid="stAlert"] {
            background: var(--hector-card) !important;
            border: 1px solid var(--hector-border) !important;
            color: var(--hector-text) !important;
            border-radius: 8px !important;
        }
        [data-testid="stAlert"] * {
            color: var(--hector-text) !important;
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

    columns = st.columns([1] * (len(items) * 2 - 1))

    for index, item in enumerate(items):
        column_index = index * 2
        with columns[column_index]:
            if index == len(items) - 1:
                st.markdown(
                    f"<div class='breadcrumbs breadcrumb-current'>{html.escape(item['label'])}</div>",
                    unsafe_allow_html=True,
                )
            else:
                if st.button(item["label"], key=f"breadcrumb-{index}-{item['label']}"):
                    item["action"]()
                    st.rerun()

        if index < len(items) - 1:
            with columns[column_index + 1]:
                st.markdown("<div class='breadcrumbs'>/</div>", unsafe_allow_html=True)


def go_home():
    st.session_state.page = "Home"


def go_to_category(category):
    st.session_state.page = "Category"
    st.session_state.category = category


def go_to_folder(category, subcategory):
    st.session_state.page = "Folder"
    st.session_state.category = category
    st.session_state.subcategory = subcategory


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
    elif item["Type"] == "Folder/Subcategory":
        button_label = f"Open {item['Category']} / {item['Subcategory']}"
        if st.button(button_label, key=f"search-folder-{item['Category']}-{item['Subcategory']}"):
            go_to_folder(item["Category"], item["Subcategory"])
            st.rerun()
    else:
        document = documents.loc[int(item["Document Index"])]
        if st.button(f"View Document: {item['Title']}", key=f"search-doc-view-{item['Document Index']}"):
            go_to_document(item["Document Index"])
            st.rerun()
        open_document_link(document)


def show_home_page():
    """Show the Hector home page with global search, categories, and admin access."""
    show_header("Hector 2.3", "Search all documents, folders, and categories.")
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
    columns = st.columns(4)

    for index, category in enumerate(MAIN_CATEGORIES):
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

    folders = load_folders()
    subcategories = folders[folders["Category"] == category]["Subcategory"].tolist()

    if not subcategories:
        st.info("No folders have been added yet. Use Admin / Manage Folders to add one.")
        return

    # Later, connect category-specific folder groups here if needed.
    for row_start in range(0, len(subcategories), 4):
        columns = st.columns(4)
        row_subcategories = subcategories[row_start : row_start + 4]

        for index, subcategory in enumerate(row_subcategories):
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
                    go_to_folder(category, subcategory)
                    st.rerun()


def show_upload_form(category, subcategory):
    """Allow users to upload documents into a selected folder."""
    st.markdown("### Upload Document")

    with st.form(f"upload-{category}-{subcategory}", clear_on_submit=True):
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

    target_folder = folder_path(category, subcategory)
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
    insert_document_record(category, subcategory, new_document)
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


def show_folder_documents(category, subcategory):
    """Show uploaded documents that belong to the current folder."""
    documents = load_documents()
    folder_documents = documents_for_folder(documents, category, subcategory)

    st.markdown("### Documents")

    if folder_documents.empty:
        st.info("No documents have been added to this folder yet.")
        return

    for index, document in folder_documents.iterrows():
        show_document_card(document, f"folder-{index}")


def show_folder_page(category, subcategory):
    """Show one folder/subcategory page with upload and document list."""
    if st.button(f"Back to {category}"):
        go_to_category(category)
        st.rerun()

    show_header(subcategory, "Documents for this subcategory will be added here.")
    show_breadcrumbs(
        [
            {"label": "Home", "action": go_home},
            {"label": category, "action": lambda: go_to_category(category)},
            {"label": subcategory, "action": lambda: go_to_folder(category, subcategory)},
        ]
    )
    show_upload_form(category, subcategory)
    show_folder_documents(category, subcategory)

    # Later, connect more document workflow fields for this folder here.


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
    subcategory = str(document["Subcategory"])
    document_name = str(document["Document Name"])

    show_header(document_name, "Document details.")
    show_breadcrumbs(
        [
            {"label": "Home", "action": go_home},
            {"label": category, "action": lambda: go_to_category(category)},
            {"label": subcategory, "action": lambda: go_to_folder(category, subcategory)},
            {"label": document_name, "action": lambda: go_to_document(document_index)},
        ]
    )
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

    show_header("Admin / Manage Folders", "Create and delete Hector folders.")
    show_breadcrumbs(
        [
            {"label": "Home", "action": go_home},
            {"label": "Admin / Manage Folders", "action": go_to_admin},
        ]
    )
    folders = load_folders()
    documents = load_documents()

    st.markdown("## Add Folder")
    with st.form("add-folder", clear_on_submit=True):
        category = st.selectbox("Main category", MAIN_CATEGORIES)
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
                    connection.execute(
                        """
                        INSERT INTO folders (name, category_id, parent_folder_id)
                        VALUES (?, ?, NULL)
                        """,
                        (folder_name, category_id),
                    )
                folder_path(category, folder_name).mkdir(parents=True, exist_ok=True)
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

    folder_labels = [f"{row['Category']} / {row['Subcategory']}" for _, row in folders.iterrows()]
    selected_label = st.selectbox("Folder to delete", folder_labels)
    selected_category, selected_subcategory = selected_label.split(" / ", 1)
    folder_documents = documents_for_folder(documents, selected_category, selected_subcategory)

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
            category_id = get_category_id(connection, selected_category)
            folder_row = connection.execute(
                "SELECT id FROM folders WHERE name = ? AND category_id = ?",
                (selected_subcategory, category_id),
            ).fetchone()

            if folder_row and delete_files:
                connection.execute("DELETE FROM documents WHERE folder_id = ?", (folder_row["id"],))

            if folder_row:
                connection.execute("DELETE FROM folders WHERE id = ?", (folder_row["id"],))

        if delete_files:
            target_folder = folder_path(selected_category, selected_subcategory)
            if target_folder.exists():
                shutil.rmtree(target_folder)

        st.success("Folder deleted.")
        st.rerun()


def main():
    st.set_page_config(page_title="Hector 2.3", layout="wide")
    ensure_storage()
    apply_styles()

    if "page" not in st.session_state:
        st.session_state.page = "Home"
    if "category" not in st.session_state:
        st.session_state.category = ""
    if "subcategory" not in st.session_state:
        st.session_state.subcategory = ""
    if "document_index" not in st.session_state:
        st.session_state.document_index = 0

    if st.session_state.page == "Home":
        show_home_page()
    elif st.session_state.page == "Category":
        show_category_page(st.session_state.category)
    elif st.session_state.page == "Folder":
        show_folder_page(st.session_state.category, st.session_state.subcategory)
    elif st.session_state.page == "Admin":
        show_admin_page()
    elif st.session_state.page == "Document":
        show_document_page(st.session_state.document_index)


if __name__ == "__main__":
    main()
