import http from "node:http";
import fs from "node:fs/promises";
import fsSync from "node:fs";
import path from "node:path";
import { Buffer } from "node:buffer";
import { DatabaseSync } from "node:sqlite";

const root = "C:/Users/Adam Samad/Documents/Codex/2026-05-21/build-a-simple-python-streamlit-app";
const dbPath = path.join(root, "hector.db");
const documentsDir = path.join(root, "documents");
const mainCategories = ["IMS", "JDS", "JSA", "ORG Chart"];
const documentHeaders = ["name", "code", "department", "keywords", "file_name", "file_path", "category_id", "folder_id"];

function db() {
  const database = new DatabaseSync(dbPath);
  database.exec("PRAGMA foreign_keys = ON");
  return database;
}

function safePart(name) {
  return String(name || "Untitled").trim().replace(/[<>:"/\\|?*]/g, "-");
}

function htmlEscape(value) {
  return String(value ?? "").replace(/[&<>"]/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
  }[char]));
}

function getCategoryId(database, category) {
  database.prepare("INSERT OR IGNORE INTO categories (name) VALUES (?)").run(category);
  return database.prepare("SELECT id FROM categories WHERE name = ?").get(category).id;
}

function getFolderId(database, category, folder) {
  const categoryId = getCategoryId(database, category);
  database
    .prepare("INSERT OR IGNORE INTO folders (name, category_id, parent_folder_id) VALUES (?, ?, NULL)")
    .run(folder, categoryId);
  return database.prepare("SELECT id FROM folders WHERE name = ? AND category_id = ?").get(folder, categoryId).id;
}

function readFolders() {
  const database = db();
  try {
    return database.prepare(`
      SELECT folders.id, folders.name, categories.name AS category
      FROM folders
      JOIN categories ON categories.id = folders.category_id
      ORDER BY categories.name, folders.name
    `).all();
  } finally {
    database.close();
  }
}

function readDocuments() {
  const database = db();
  try {
    return database.prepare(`
      SELECT
        documents.id,
        documents.name,
        documents.code,
        documents.department,
        documents.keywords,
        documents.file_name,
        documents.file_path,
        documents.uploaded_at,
        categories.name AS category,
        folders.name AS folder
      FROM documents
      JOIN categories ON categories.id = documents.category_id
      LEFT JOIN folders ON folders.id = documents.folder_id
      ORDER BY documents.name
    `).all();
  } finally {
    database.close();
  }
}

function makeIndex() {
  const folders = readFolders();
  const documents = readDocuments();
  const index = [];

  for (const category of mainCategories) {
    index.push({
      type: "Main Category",
      title: category,
      subtitle: "Main Hector category",
      searchText: category,
      url: `/category?name=${encodeURIComponent(category)}`,
    });
  }

  for (const folder of folders) {
    index.push({
      type: "Folder/Subcategory",
      title: folder.name,
      subtitle: `${folder.category} folder`,
      searchText: `${folder.category} ${folder.name}`,
      url: `/folder?id=${folder.id}`,
    });
  }

  for (const document of documents) {
    index.push({
      type: "Document",
      title: document.name,
      documentId: document.id,
      subtitle: `${document.code || ""} | ${document.department || ""} | ${document.category} / ${document.folder || ""}`,
      searchText: [
        document.name,
        document.code,
        document.department,
        document.keywords,
        document.category,
        document.folder,
      ].join(" "),
      url: `/document?id=${document.id}`,
    });
  }

  return index;
}

function pageShell(body) {
  return `<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Hector 2.1</title>
  <style>
    body{margin:0;background:#F5F7FA;color:#111827;font-family:Arial,sans-serif;font-size:17px;line-height:1.5}
    main{max-width:1180px;margin:0 auto;padding:32px 22px}
    .header{background:#1E3A8A;color:white;padding:28px;border-radius:10px;margin-bottom:24px}
    .header h1,.header p{color:white;margin:0}.header p{margin-top:8px}
    .grid{display:grid;grid-template-columns:repeat(4,1fr);gap:18px}
    .card,.panel,.result{background:white;border:1px solid #E5E7EB;border-radius:10px;padding:18px;margin:14px 0;box-shadow:0 1px 3px rgba(17,24,39,.06)}
    .card,.result{cursor:pointer}.card:hover,.result:hover{border-color:#2563EB}
    h1,h2,h3{color:#1E3A8A}.muted{color:#4B5563}
    .btn,button{display:inline-block;background:#2563EB;color:white;border:0;border-radius:8px;padding:10px 14px;font-weight:700;text-decoration:none;cursor:pointer;margin:4px 4px 4px 0}
    input,select{padding:12px;border:1px solid #E5E7EB;border-radius:8px;margin:4px 0 12px;width:100%;max-width:650px;font-size:17px}
    .pill{display:inline-block;background:#EFF6FF;color:#1E3A8A;border:1px solid #BFDBFE;border-radius:999px;padding:3px 10px;font-weight:700;font-size:14px}
    .danger{background:#991B1B}.warn{color:#991B1B;font-weight:700}
    .open-error{display:none;background:#FEF2F2;color:#991B1B;border:1px solid #FECACA;border-radius:8px;padding:10px 12px;margin:10px 0;font-weight:700}
    .breadcrumbs{margin:-8px 0 18px;color:#4B5563}
    .breadcrumbs a{color:#2563EB;text-decoration:none;font-weight:700}
    .breadcrumbs a:hover{text-decoration:underline;cursor:pointer}
    .breadcrumb-current{color:#111827;font-weight:700}
    @media(max-width:900px){.grid{grid-template-columns:1fr}}
  </style>
</head>
<body><main>${body}</main>
  <script>
    async function openDocument(documentId) {
      console.log("Open Document clicked", documentId);
      const errorBox = document.getElementById("open-error-" + documentId);
      if (errorBox) {
        errorBox.style.display = "none";
        errorBox.textContent = "";
      }
      try {
        const statusResponse = await fetch("/document-status?id=" + encodeURIComponent(documentId));
        const status = await statusResponse.json();
        if (!status.ok) {
          const message = status.message || "Document file not found";
          if (errorBox) {
            errorBox.textContent = message;
            errorBox.style.display = "block";
          } else {
            alert(message);
          }
          return;
        }
        window.open("/open-document?id=" + encodeURIComponent(documentId), "_blank", "noopener");
      } catch (error) {
        const message = "Could not open document. Please try again.";
        if (errorBox) {
          errorBox.textContent = message;
          errorBox.style.display = "block";
        } else {
          alert(message);
        }
      }
    }
  </script>
</body></html>`;
}

function breadcrumbs(items) {
  return `<nav class="breadcrumbs">${items.map((item, index) => {
    const label = htmlEscape(item.label);
    if (index === items.length - 1) {
      return `<span class="breadcrumb-current">${label}</span>`;
    }
    return `<a href="${item.url}">${label}</a>`;
  }).join(" / ")}</nav>`;
}

function redirect(response, location) {
  response.writeHead(302, { Location: location });
  response.end();
}

async function readBody(request) {
  const chunks = [];
  for await (const chunk of request) {
    chunks.push(chunk);
  }
  return Buffer.concat(chunks).toString("utf8");
}

function parseForm(text) {
  return Object.fromEntries(new URLSearchParams(text));
}

function docCard(document) {
  return `<div class="card">
    <h3>${htmlEscape(document.name)}</h3>
    <p class="muted">${htmlEscape(document.code || "")} | ${htmlEscape(document.department || "")} | ${htmlEscape(document.category)} / ${htmlEscape(document.folder || "")}</p>
    <p><b>Keywords:</b> ${htmlEscape(document.keywords || "")}</p>
    <p><b>File:</b> ${htmlEscape(document.file_name)}</p>
    <div id="open-error-${htmlEscape(document.id)}" class="open-error"></div>
    <button type="button" onclick="openDocument(${Number(document.id)})">Open Document</button>
  </div>`;
}

async function renderHome(response) {
  const searchIndex = makeIndex();
  const cards = mainCategories.map((category) => `<div class="card" onclick="location.href='/category?name=${encodeURIComponent(category)}'">
    <h2>${htmlEscape(category)}</h2>
    <p class="muted">Open ${htmlEscape(category)}</p>
    <a class="btn" href="/category?name=${encodeURIComponent(category)}">Open ${htmlEscape(category)}</a>
  </div>`).join("");

  response.end(pageShell(`
    <div class="header"><h1>Hector 2.1</h1><p>Search all categories, folders, and documents.</p></div>
    ${breadcrumbs([{ label: "Home", url: "/" }])}
    <div class="panel">
      <h2>Global Search</h2>
      <input id="globalSearch" autocomplete="off" placeholder="Try assets, main, qhs, operations, document code, or keywords">
      <div id="searchResults"></div>
    </div>
    <h2>Main Categories</h2>
    <div class="grid">${cards}</div>
    <h2>Admin</h2>
    <a class="btn" href="/admin">Admin / Manage Folders</a>
    <script>
      const searchIndex = ${JSON.stringify(searchIndex).replaceAll("<", "\\u003c")};
      const input = document.getElementById("globalSearch");
      const resultsBox = document.getElementById("searchResults");

      function matches(text, query) {
        text = String(text || "").toLowerCase();
        query = String(query || "").trim().toLowerCase();
        if (!query) return false;
        const words = text.replaceAll("-", " ").replaceAll("/", " ").split(/\\s+/);
        return text.includes(query) || words.some((word) => word.startsWith(query));
      }

      function renderSearch() {
        const query = input.value;
        resultsBox.replaceChildren();
        if (!query.trim()) return;
        const results = searchIndex.filter((item) => matches(item.searchText, query));
        if (!results.length) {
          const empty = document.createElement("p");
          empty.className = "warn";
          empty.textContent = "No results found.";
          resultsBox.appendChild(empty);
          return;
        }
        for (const item of results) {
          const result = document.createElement("div");
          result.className = "result";
          result.onclick = () => { location.href = item.url; };
          result.innerHTML = '<span class="pill"></span><h3></h3><p class="muted"></p><div class="open-error"></div><a class="btn"></a><button type="button" style="display:none">Open Document</button>';
          result.querySelector(".pill").textContent = item.type;
          result.querySelector("h3").textContent = item.title;
          result.querySelector("p").textContent = item.subtitle;
          result.querySelector("a").href = item.url;
          result.querySelector("a").textContent = item.type === "Document" ? "View Document" : "Open";
          const openButton = result.querySelector("button");
          const errorBox = result.querySelector(".open-error");
          if (item.type === "Document") {
            errorBox.id = "open-error-search-" + item.documentId;
            openButton.style.display = "inline-block";
            openButton.onclick = (event) => {
              event.stopPropagation();
              errorBox.id = "open-error-" + item.documentId;
              openDocument(item.documentId);
            };
          }
          resultsBox.appendChild(result);
        }
      }
      input.addEventListener("input", renderSearch);
    </script>
  `));
}

async function renderCategory(response, category) {
  const database = db();
  try {
    const categoryRow = database.prepare("SELECT id, name FROM categories WHERE name = ?").get(category);
    if (!categoryRow) {
      response.end(pageShell(`<div class="header"><h1>Category Not Found</h1></div>`));
      return;
    }
    const folders = database.prepare("SELECT id, name FROM folders WHERE category_id = ? ORDER BY name").all(categoryRow.id);
    const cards = folders.map((folder) => `<div class="card" onclick="location.href='/folder?id=${folder.id}'">
      <div style="font-size:30px">Folder</div>
      <h3>${htmlEscape(folder.name)}</h3>
      <p class="muted">Open ${htmlEscape(folder.name)}</p>
      <a class="btn" href="/folder?id=${folder.id}">Open</a>
    </div>`).join("") || "<p>No folders yet. Use Admin / Manage Folders to add one.</p>";

    response.end(pageShell(`<a class="btn" href="/">Back to Home</a>
      <div class="header"><h1>${htmlEscape(categoryRow.name)}</h1><p>Choose a folder.</p></div>
      ${breadcrumbs([{ label: "Home", url: "/" }, { label: categoryRow.name, url: `/category?name=${encodeURIComponent(categoryRow.name)}` }])}
      <div class="grid">${cards}</div>`));
  } finally {
    database.close();
  }
}

async function renderFolder(response, folderId) {
  const database = db();
  try {
    const folder = database.prepare(`
      SELECT folders.id, folders.name, categories.name AS category
      FROM folders
      JOIN categories ON categories.id = folders.category_id
      WHERE folders.id = ?
    `).get(Number(folderId));
    if (!folder) {
      response.end(pageShell(`<div class="header"><h1>Folder Not Found</h1></div>`));
      return;
    }
    const documents = database.prepare(`
      SELECT documents.*, categories.name AS category, folders.name AS folder
      FROM documents
      JOIN categories ON categories.id = documents.category_id
      LEFT JOIN folders ON folders.id = documents.folder_id
      WHERE documents.folder_id = ?
      ORDER BY documents.name
    `).all(folder.id);
    const list = documents.map(docCard).join("") || "<p>No documents have been added to this folder yet.</p>";

    response.end(pageShell(`<a class="btn" href="/category?name=${encodeURIComponent(folder.category)}">Back to ${htmlEscape(folder.category)}</a>
      <div class="header"><h1>${htmlEscape(folder.name)}</h1><p>Documents for this subcategory.</p></div>
      ${breadcrumbs([
        { label: "Home", url: "/" },
        { label: folder.category, url: `/category?name=${encodeURIComponent(folder.category)}` },
        { label: folder.name, url: `/folder?id=${folder.id}` },
      ])}
      <div class="panel">
        <h2>Upload Document</h2>
        <form method="post" action="/upload-json">
          <input type="hidden" name="folderId" value="${folder.id}">
          <label>Document file</label>
          <input id="file" type="file" accept=".pdf,.doc,.docx,.xls,.xlsx" required>
          <input type="hidden" id="fileName" name="fileName">
          <input type="hidden" id="fileData" name="fileData">
          <label>Document name</label><input name="documentName" required>
          <label>Document code</label><input name="code">
          <label>Department</label><input name="department">
          <label>Keywords</label><input name="keywords">
          <label>Related documents</label><input name="related">
          <button>Upload Document</button>
        </form>
        <script>
          document.querySelector("form").addEventListener("submit", (event) => {
            const file = document.getElementById("file").files[0];
            if (!file) return;
            event.preventDefault();
            const reader = new FileReader();
            reader.onload = () => {
              document.getElementById("fileName").value = file.name;
              document.getElementById("fileData").value = reader.result.split(",")[1];
              event.target.submit();
            };
            reader.readAsDataURL(file);
          });
        </script>
      </div>
      <h2>Documents</h2>${list}`));
  } finally {
    database.close();
  }
}

async function renderDocument(response, documentId) {
  const database = db();
  try {
    const document = database.prepare(`
      SELECT documents.*, categories.name AS category, folders.name AS folder, folders.id AS folder_id
      FROM documents
      JOIN categories ON categories.id = documents.category_id
      LEFT JOIN folders ON folders.id = documents.folder_id
      WHERE documents.id = ?
    `).get(Number(documentId));
    if (!document) {
      response.end(pageShell(`<div class="header"><h1>Document Not Found</h1></div>${breadcrumbs([{ label: "Home", url: "/" }, { label: "Document Not Found", url: "/" }])}`));
      return;
    }
    response.end(pageShell(`
      <div class="header"><h1>${htmlEscape(document.name)}</h1><p>Document details.</p></div>
      ${breadcrumbs([
        { label: "Home", url: "/" },
        { label: document.category, url: `/category?name=${encodeURIComponent(document.category)}` },
        { label: document.folder || "Folder", url: `/folder?id=${document.folder_id}` },
        { label: document.name, url: `/document?id=${document.id}` },
      ])}
      ${docCard(document)}
    `));
  } finally {
    database.close();
  }
}

async function renderAdmin(response, message = "") {
  const folders = readFolders();
  const categoryOptions = mainCategories.map((category) => `<option>${category}</option>`).join("");
  const folderOptions = folders.map((folder) => `<option value="${folder.id}">${htmlEscape(folder.category)} / ${htmlEscape(folder.name)}</option>`).join("");
  response.end(pageShell(`<a class="btn" href="/">Back to Home</a>
    <div class="header"><h1>Admin / Manage Folders</h1><p>Create and delete Hector folders.</p></div>
    ${breadcrumbs([{ label: "Home", url: "/" }, { label: "Admin / Manage Folders", url: "/admin" }])}
    ${message ? `<p class="warn">${htmlEscape(message)}</p>` : ""}
    <div class="panel"><h2>Add Folder</h2>
      <form method="post" action="/admin/add">
        <label>Main category</label><select name="category">${categoryOptions}</select>
        <label>New folder/subcategory name</label><input name="subcategory" required>
        <button>Add Folder</button>
      </form>
    </div>
    <div class="panel"><h2>Delete Folder</h2>
      <form method="post" action="/admin/delete">
        <label>Folder to delete</label><select name="folderId">${folderOptions}</select>
        <p class="warn">If this folder contains documents, Hector will ask for confirmation.</p>
        <label><input style="width:auto" type="checkbox" name="confirm" value="yes"> I understand and want to delete this folder.</label><br>
        <label><input style="width:auto" type="checkbox" name="deleteFiles" value="yes"> Also delete document records and files in this folder.</label><br>
        <button class="danger">Delete Folder</button>
      </form>
    </div>`));
}

async function handleUpload(request, response) {
  const form = parseForm(await readBody(request));
  const database = db();
  try {
    const folder = database.prepare(`
      SELECT folders.id, folders.name, folders.category_id, categories.name AS category
      FROM folders
      JOIN categories ON categories.id = folders.category_id
      WHERE folders.id = ?
    `).get(Number(form.folderId));
    if (!folder) return renderAdmin(response, "Folder not found.");
    const fileName = safePart(form.fileName);
    const targetFolder = path.join(documentsDir, safePart(folder.category), safePart(folder.name));
    await fs.mkdir(targetFolder, { recursive: true });
    const absoluteFilePath = path.join(targetFolder, fileName);
    const storedFilePath = path.relative(root, absoluteFilePath).split(path.sep).join("/");
    await fs.writeFile(absoluteFilePath, Buffer.from(form.fileData || "", "base64"));
    database.prepare(`
      INSERT OR IGNORE INTO documents (name, code, department, keywords, file_name, file_path, category_id, folder_id)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    `).run(form.documentName || fileName, form.code || "", form.department || "", form.keywords || "", fileName, storedFilePath, folder.category_id, folder.id);
    redirect(response, `/folder?id=${folder.id}`);
  } finally {
    database.close();
  }
}

async function handleAddFolder(request, response) {
  const form = parseForm(await readBody(request));
  const folderName = String(form.subcategory || "").trim().toUpperCase();
  if (!folderName) return renderAdmin(response, "Please enter a folder name.");
  const database = db();
  try {
    const categoryId = getCategoryId(database, form.category);
    database.prepare("INSERT INTO folders (name, category_id, parent_folder_id) VALUES (?, ?, NULL)").run(folderName, categoryId);
    await fs.mkdir(path.join(documentsDir, safePart(form.category), safePart(folderName)), { recursive: true });
    redirect(response, `/category?name=${encodeURIComponent(form.category)}`);
  } catch (error) {
    renderAdmin(response, "That folder already exists.");
  } finally {
    database.close();
  }
}

async function handleDeleteFolder(request, response) {
  const form = parseForm(await readBody(request));
  const folderId = Number(form.folderId);
  const database = db();
  try {
    const folder = database.prepare(`
      SELECT folders.id, folders.name, categories.name AS category
      FROM folders
      JOIN categories ON categories.id = folders.category_id
      WHERE folders.id = ?
    `).get(folderId);
    if (!folder) return renderAdmin(response, "Folder not found.");
    const count = database.prepare("SELECT COUNT(*) AS count FROM documents WHERE folder_id = ?").get(folderId).count;
    if (form.confirm !== "yes") return renderAdmin(response, "Please confirm before deleting this folder.");
    if (count && form.deleteFiles !== "yes") return renderAdmin(response, "This folder contains documents. Are you sure you want to delete it? Confirm document deletion or move them first.");
    if (form.deleteFiles === "yes") {
      database.prepare("DELETE FROM documents WHERE folder_id = ?").run(folderId);
      await fs.rm(path.join(documentsDir, safePart(folder.category), safePart(folder.name)), { recursive: true, force: true });
    }
    database.prepare("DELETE FROM folders WHERE id = ?").run(folderId);
    redirect(response, "/admin");
  } finally {
    database.close();
  }
}

function getDocumentFileInfo(database, documentId) {
  const document = database.prepare("SELECT id, name, file_name, file_path FROM documents WHERE id = ?").get(Number(documentId));
  if (!document || !document.file_path) {
    return { ok: false, message: "Document file not found" };
  }

  const resolved = path.isAbsolute(document.file_path)
    ? path.resolve(document.file_path)
    : path.resolve(root, document.file_path);
  const documentsRoot = path.resolve(documentsDir);

  if (!resolved.startsWith(documentsRoot + path.sep) && resolved !== documentsRoot) {
    return { ok: false, message: "File path is outside the documents folder." };
  }

  if (!fsSync.existsSync(resolved)) {
    return { ok: false, message: "Document file not found" };
  }

  return {
    ok: true,
    path: resolved,
    fileName: document.file_name || path.basename(resolved),
  };
}

function documentStatus(response, documentId) {
  const database = db();
  try {
    const fileInfo = getDocumentFileInfo(database, documentId);
    response.writeHead(fileInfo.ok ? 200 : 404, { "Content-Type": "application/json" });
    response.end(JSON.stringify({
      ok: fileInfo.ok,
      message: fileInfo.ok ? "" : fileInfo.message,
    }));
  } finally {
    database.close();
  }
}

function serveDocument(response, documentId) {
  const database = db();
  try {
    const fileInfo = getDocumentFileInfo(database, documentId);
    if (!fileInfo.ok) {
      response.writeHead(fileInfo.message.includes("outside") ? 403 : 404, { "Content-Type": "text/plain; charset=utf-8" });
      response.end(fileInfo.message);
      return;
    }
    const type = fileInfo.path.toLowerCase().endsWith(".pdf") ? "application/pdf" : "application/octet-stream";
    response.writeHead(200, {
      "Content-Type": type,
      "Content-Disposition": `inline; filename*=UTF-8''${encodeURIComponent(fileInfo.fileName)}`,
    });
    fsSync.createReadStream(fileInfo.path).pipe(response);
  } finally {
    database.close();
  }
}

async function handleRequest(request, response) {
  try {
    const url = new URL(request.url, "http://localhost:8501");
    if (request.method === "GET" && url.pathname === "/") return renderHome(response);
    if (request.method === "GET" && url.pathname === "/category") return renderCategory(response, url.searchParams.get("name") || "IMS");
    if (request.method === "GET" && url.pathname === "/folder") return renderFolder(response, url.searchParams.get("id") || "");
    if (request.method === "GET" && url.pathname === "/document") return renderDocument(response, url.searchParams.get("id") || "");
    if (request.method === "GET" && url.pathname === "/admin") return renderAdmin(response);
    if (request.method === "GET" && url.pathname === "/document-status") return documentStatus(response, url.searchParams.get("id") || "");
    if (request.method === "GET" && url.pathname === "/file") return serveDocument(response, url.searchParams.get("id") || "");
    if (request.method === "GET" && url.pathname === "/open-document") return serveDocument(response, url.searchParams.get("id") || "");
    if (request.method === "POST" && url.pathname === "/upload-json") return handleUpload(request, response);
    if (request.method === "POST" && url.pathname === "/admin/add") return handleAddFolder(request, response);
    if (request.method === "POST" && url.pathname === "/admin/delete") return handleDeleteFolder(request, response);
    response.writeHead(404); response.end("Not found");
  } catch (error) {
    response.writeHead(500, { "Content-Type": "text/plain" });
    response.end(String(error.stack || error));
  }
}

if (globalThis.hectorServer) {
  await new Promise((resolve) => globalThis.hectorServer.close(resolve));
}
globalThis.hectorServer = http.createServer(handleRequest);
await new Promise((resolve) => globalThis.hectorServer.listen(8501, "127.0.0.1", resolve));
