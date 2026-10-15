# KAI - Architecture

KAI is a personal AI assistant that runs on your own computer. You can use it in the terminal or in a browser. This document explains how the pieces fit together, so you can read, change or explain the code with confidence.

## 1. The big picture

```
 Terminal (main.py)          Browser (index.html)
        |                           |
        |                    HTTP + streaming
        |                           |
        |                  web_server.py  (KaiState, Handler)
        |                           |
        +-----------+---------------+
                    |
              assistant.py  (Assistant: the chat loop)
                    |
     +--------------+-------------------+
     |              |                   |
 Model providers   tools.py         Storage
 - Ollama (local)  (10 tools)       - chat_history.jsonl / chats/*  (chat_store.py)
 - Gemini                           - memory.json                   (memory.py)
 - Mistral                          - documents per chat            (documents.py)
                                    - workspace/ (file tools)
```

One idea runs through everything: **`assistant.py` is the only place that talks to an AI model.** The terminal and the website are two thin "front doors" on top of the same brain.

## 2. Files and what each one does

| File | Job |
|---|---|
| `main.py` | Terminal app. Reads what you type, prints streamed answers, asks yes/no for sensitive actions. |
| `web_server.py` | Website server using only Python's standard library (`ThreadingHTTPServer`). No Flask or FastAPI. |
| `index.html` | The whole website: HTML, CSS and JavaScript in one file. |
| `assistant.py` | The core: system prompt, the three model providers, streaming, history, the tool-calling loop, safety checks. |
| `tools.py` | The 10 tools the model can call, plus their schemas and the `execute_tool` dispatcher. |
| `config.py` | Reads settings from `.env` into small config objects (provider, model name, limits, persona). |
| `memory.py` | Long-term memory in `memory.json` (`LongTermMemory`). |
| `chat_store.py` | Several saved chats for the website, one small file each in `chats/` (`ChatStore`). |
| `documents.py` | Reads PDF, Word and text files, splits them into chunks and picks the useful ones (`ChatDocuments`). |
| `voice.py` | Optional voice mode (wake word, speech in and out). |
| `test_*.py` | Tests using `unittest`. |

## 3. Request flow: what happens when you send a message

1. **Front door.** The terminal reads a line, or the browser sends `POST /api/chat`.
2. **Document context (website only).** If the chat has attached documents, `documents.build_context` finds the passages that match your question. They are passed to the assistant as temporary context, not stored in history.
3. **`Assistant.chat()`** adds your message to the history and enters the loop in `_chat_inner`.
4. **Call the model.** The history is converted to the format of the chosen provider and sent. Replies stream back token by token.
5. **Did the model ask for tools?**
   - **Yes:** each tool call is run through `execute_tool`, the result is added to the history as a `tool` message, and the loop goes back to step 4 so the model can read the result.
   - **No:** the text is the final answer. It is saved and returned.
6. **Safety stop.** The loop runs at most `MAX_TOOL_ITERATIONS` times (default 8). After that it stops with a message instead of looping forever.

```
user message -> history -> model -> tool call? --yes--> run tool -> result to history -+
                              ^                  |                                      |
                              |                  no                                     |
                              +------------------+--> final answer                     |
                              +---------------------------------------------------------+
```

## 4. Model providers

`Assistant` supports three providers, chosen with `MODEL_PROVIDER` in `.env`:

| Provider | How it is called | Notes |
|---|---|---|
| **Ollama** | Local HTTP API (`OLLAMA_BASE_URL`, default `http://localhost:11434`) | No API key, chat stays on your machine. Recommended model: `qwen2.5:7b`. `OLLAMA_NUM_CTX` sets context size. |
| **Gemini** | Google's native REST API | Needs `GEMINI_API_KEY`. History is converted by `_messages_to_gemini` and cleaned by `sanitize_gemini_contents`. |
| **Mistral** | OpenAI-style chat API | Needs `MISTRAL_API_KEY`. |

Each provider answers in a slightly different shape. The functions `_gemini_to_openai` and `_ollama_to_openai` convert replies into one shared shape, so the chat loop only has to understand one format. Ollama needs one more fix: `ollama_messages` turns saved tool-call arguments from text back into objects.

**Streaming** is handled in `_complete_stream`. `LinkFlattener` rewrites markdown links into plain text as they stream, because the replies are shown as plain text.

**Retries.** `request_with_retry` retries temporary failures with exponential backoff. If a rate limit (429) still fails, the user gets a clear message.

## 5. Conversation history

`ChatHistory` keeps the messages and keeps them valid:

- **`repair_history_body`** fixes broken sequences, for example a tool call with no result.
- **`truncate`** keeps the history inside the model's limit. It first shrinks old tool results (`MAX_TOOL_RESULT_CHARS`, default 4000), then drops the oldest whole turns. Dropping a whole turn avoids leaving a tool result with no matching call.
- **`save` / `load`** write and read the history as JSONL.

## 6. Tools

`tools.py` defines each tool as a `ToolSchema` (name, description, parameters). `execute_tool` finds the tool by name and runs it. Errors are returned as text, so the model can read them and explain them.

| Tool | What it does |
|---|---|
| `get_current_time`, `get_current_date` | Time and date, with an optional time zone (`_zone`; needs `tzdata` on Windows). |
| `read_file`, `write_file`, `list_files` | File access limited to the `workspace/` folder (`resolve_workspace_path`). |
| `calculate` | Safe maths using Python's `ast` module (no `eval`), with a guard for huge powers (`_check_power`). |
| `web_search` | DuckDuckGo through the `ddgs` package. No API key. Returns 3 to 8 results. |
| `web_fetch` | Reads a public web page. See the safety section below. |
| `remember`, `recall_memory` | Save and read long-term facts in `memory.json`. |

`memory.py` ignores facts that are already saved, comparing case-insensitively.

## 7. Documents (PDF, Word, text Q&A)

Per chat, the user can attach up to 5 files of up to 5 MB each (`MAX_DOCS_PER_CHAT`, `MAX_UPLOAD_BYTES`).

1. **Extract:** `extract_text` reads `.pdf` (with `pypdf`), `.docx` (by unzipping and reading the XML) and plain text.
2. **Chunk:** `split_chunks` cuts the text into pieces of about 1200 characters with a 150-character overlap, preferring to cut at line or sentence ends.
3. **Pick:** `pick_chunks` scores each chunk by how many of the question's words it contains, giving rare words more weight (an IDF-style keyword score). The top 4 chunks win.
4. **Inject:** `build_context` puts those chunks in front of the model for this question only.

This is simple keyword retrieval. It needs no embeddings and no extra model, so it works offline. The trade-off is that it matches words, not meaning.

## 8. Website server

`web_server.py` has two main parts:

- **`KaiState`** holds what the server shares: the assistant, a lock so only one chat runs at a time ("busy"), and pending approvals.
- **`Handler`** answers HTTP requests.

| Endpoint | Purpose |
|---|---|
| `GET /` | Serves `index.html`. |
| `GET /api/state` | Current chat, settings, persona, documents. |
| `POST /api/chat`, `/api/regenerate` | Send a message or retry the last one. The answer streams back as server-sent events (`text/event-stream`). |
| `POST /api/confirm` | The user's yes or no for an approval prompt. |
| `POST /api/chat/new`, `/open`, `/delete`, `/api/chats` | Manage saved chats. |
| `POST /api/upload`, `/api/docs/remove` | Attach or remove documents. |
| `POST /api/persona`, `/api/model`, `/api/models`, `/api/tools`, `/api/memory`, `/api/clear` | Settings, model choice, tool switch, memory, clearing a chat. |

The browser page draws markdown with safe DOM calls only (no raw HTML injection).

## 9. Safety design

Safety is part of the design, not an add-on. The main layers:

| Risk | Defence |
|---|---|
| **Prompt injection.** A web page or document tries to give the model orders. | After any `web_fetch` or `web_search` result is in the chat, the sensitive tools `write_file` and `remember` need the user's approval (`SENSITIVE_AFTER_WEB`, `_user_approves`). |
| **SSRF.** The model is tricked into fetching internal addresses. | `_check_public_url` allows public IP addresses only and checks them again after every redirect. |
| **File access outside the workspace.** | `resolve_workspace_path` keeps all file tools inside `workspace/`. |
| **Heavy or dangerous maths.** | `calculate` uses a restricted `ast` evaluator with limits. |
| **Other websites talking to your KAI.** | The server listens on localhost only and checks the `Host` and `Origin` headers. Request bodies have size limits (64 KB, or 8 MB for uploads). |
| **Secrets in Git.** | `.env`, `memory.json`, `persona.json`, `chats/` and chat history are in `.gitignore`. `env.example` holds placeholders only. |
| **False claims.** | The system prompt tells KAI to claim only what is saved in memory and not to claim abilities it lacks (reminders, calls, email). |

## 10. Data and storage

| What | Where | Notes |
|---|---|---|
| Terminal chat | `chat_history.jsonl` | Saved and loaded by `ChatHistory`. |
| Website chats | `chats/<id>.jsonl` (+ `chats/<id>.docs.json` for attached documents) | One file per chat; ids are validated by `ChatStore.valid_id`. |
| Long-term memory | `memory.json` | Shared by the terminal and the website. |
| Persona | `persona.json` | Name, role, tone and extra instructions from the Settings page. |
| Workspace files | `workspace/` | The only folder the file tools can reach. |

All of it stays on your computer.

## 11. Configuration

Settings come from `.env`, read by `config.py`. The most important ones:

| Variable | Meaning |
|---|---|
| `MODEL_PROVIDER` | `ollama`, `gemini` or `mistral` |
| `MODEL_NAME` | Model to use (each provider has a default) |
| `GEMINI_API_KEY`, `MISTRAL_API_KEY` | Keys for the cloud providers |
| `OLLAMA_BASE_URL`, `OLLAMA_NUM_CTX` | Local Ollama address and context size |
| `MAX_TOOL_ITERATIONS`, `MAX_TOOL_RESULT_CHARS` | Limits for the tool loop |
| `ASSISTANT_NAME`, `ASSISTANT_ROLE`, `ASSISTANT_TONE`, `ASSISTANT_INSTRUCTIONS` | Default persona |
| `VOICE_WAKE_WORD` | Wake word for voice mode (default `hey kai`) |

## 12. Testing

Tests use `unittest` and cover each layer:

| Test file | Covers |
|---|---|
| `test_history.py` | History repair and truncation |
| `test_errors.py` | Error messages and retries |
| `test_ollama.py` | Ollama message conversion |
| `test_tools.py`, `test_web_fetch.py`, `test_web_search.py` | Tools |
| `test_security.py` | Approval rules, SSRF and sandbox checks |
| `test_prompt.py` | System prompt rules |
| `test_memory.py`, `test_links.py` | Memory and link flattening |
| `test_config.py` | Settings, default model, friendly errors for bad numbers |
| `test_documents.py` | Document reading and retrieval |
| `test_web_server.py` | Website endpoints and request checks |

Run them all with `python -m unittest`.

## 13. Design choices and trade-offs

- **Standard-library server.** Fewer dependencies and easy to understand. The trade-off is that you write routing and streaming by hand.
- **One assistant, two front doors.** The terminal and the website share the same logic, so a fix in one place helps both.
- **Keyword retrieval instead of embeddings.** It works offline and has nothing to install. It will miss answers that use different words from the question.
- **Local first.** Ollama keeps chats private. Cloud providers are optional.
- **Approval over blocking.** Web content is useful, so KAI does not forbid it. It asks you before it saves anything after reading the web.
- **One request at a time.** The "busy" lock keeps the single assistant state consistent. It also means one browser tab chats at a time.

## 14. Ideas for next steps

- Embedding-based document search, for matches by meaning.
- An Android app that talks to the same server (the server API already returns JSON and streams).
- Optional login, if the server is ever exposed beyond localhost.
- A short demo video linked from the README.
