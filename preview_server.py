import csv
import html
import http.server
import mimetypes
from pathlib import Path
import socketserver
import urllib.parse


PORT = 8501
CSV_FILE = "documents.csv"
DOCUMENT_FOLDER = Path("documents")
MISSING_FILE_MESSAGE = "Document file not found. Please check the file name and documents folder."


def load_documents():
    with open(CSV_FILE, newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def search_documents(documents, query):
    if not query:
        return documents

    query = query.lower()
    search_fields = ["Document Name", "Code", "Department", "Keywords"]

    return [
        document
        for document in documents
        if any(query in document[field].lower() for field in search_fields)
    ]


def find_document(documents, code):
    for document in documents:
        if document["Code"] == code:
            return document
    return documents[0] if documents else None


def page(documents, results, selected, query):
    options = "\n".join(
        f'<li><a href="/?q={urllib.parse.quote(query)}&code={html.escape(doc["Code"])}">'
        f'{html.escape(doc["Code"])} - {html.escape(doc["Document Name"])}</a></li>'
        for doc in results
    )

    related_links = ""
    for code in [item.strip() for item in selected["Related Documents"].split(",") if item.strip()]:
        related = find_document(documents, code)
        if related:
            related_links += (
                f'<li><a href="/?code={html.escape(related["Code"])}">'
                f'{html.escape(related["Code"])} - {html.escape(related["Document Name"])}</a></li>'
            )

    file_name = selected["File Name"].strip()
    file_path = DOCUMENT_FOLDER / file_name
    if file_name and file_path.exists():
        open_button = f'<a href="/documents/{urllib.parse.quote(file_name)}" target="_blank">Open Document</a>'
    else:
        open_button = f'<p>{MISSING_FILE_MESSAGE}</p>'

    return f"""<!doctype html>
<html>
<head>
  <title>Hector</title>
  <style>
    body {{ font-family: Arial, sans-serif; max-width: 900px; margin: 40px auto; padding: 0 20px; }}
    input {{ width: 100%; padding: 12px; font-size: 16px; }}
    a {{ color: #0b66c3; text-decoration: none; }}
    .box {{ border: 1px solid #ddd; border-radius: 8px; padding: 20px; margin-top: 24px; }}
    .muted {{ color: #666; }}
  </style>
</head>
<body>
  <h1>Hector</h1>
  <p class="muted">Search company procedure documents.</p>
  <form method="get">
    <input name="q" value="{html.escape(query)}" placeholder="Search by name, code, department, or keywords">
  </form>
  <h2>Documents</h2>
  <ul>{options}</ul>
  <div class="box">
    <h2>{html.escape(selected["Document Name"])}</h2>
    <p><b>Code:</b> {html.escape(selected["Code"])}</p>
    <p><b>Department:</b> {html.escape(selected["Department"])}</p>
    <p><b>Keywords:</b> {html.escape(selected["Keywords"])}</p>
    <p><b>File Name:</b> {html.escape(selected["File Name"])}</p>
    <p>{open_button}</p>
    <h3>Related Documents</h3>
    <ul>{related_links or "<li>No related documents listed.</li>"}</ul>
  </div>
</body>
</html>"""


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed_url = urllib.parse.urlparse(self.path)

        if parsed_url.path.startswith("/documents/"):
            self.serve_document(parsed_url.path)
            return

        documents = load_documents()
        params = urllib.parse.parse_qs(parsed_url.query)
        query = params.get("q", [""])[0]
        selected_code = params.get("code", [""])[0]
        results = search_documents(documents, query)
        selected = find_document(documents, selected_code) or (results[0] if results else documents[0])
        content = page(documents, results, selected, query).encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def serve_document(self, url_path):
        file_name = urllib.parse.unquote(url_path.removeprefix("/documents/"))
        file_path = (DOCUMENT_FOLDER / file_name).resolve()
        documents_path = DOCUMENT_FOLDER.resolve()

        if not str(file_path).startswith(str(documents_path)) or not file_path.exists():
            content = MISSING_FILE_MESSAGE.encode("utf-8")
            self.send_response(404)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return

        file_type, _ = mimetypes.guess_type(file_path)
        file_type = file_type or "application/octet-stream"
        content = file_path.read_bytes()

        self.send_response(200)
        self.send_header("Content-Type", file_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


with socketserver.TCPServer(("", PORT), Handler) as server:
    print(f"Hector preview running at http://localhost:{PORT}")
    server.serve_forever()
