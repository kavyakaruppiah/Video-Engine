# Technology research

Research date: 2026-10-20. Re-check versions and licences before distribution.

| Dependency | Official source | Licence | Purpose | Status |
|---|---|---|---|---|
| FastAPI | https://github.com/fastapi/fastapi | MIT | API and OpenAPI | Used |
| Pydantic | https://github.com/pydantic/pydantic | MIT | Strict schemas | Used |
| SQLite | https://www.sqlite.org/ | Public domain | Project/history persistence | Used |
| FFmpeg/FFprobe | https://ffmpeg.org/ | LGPL/GPL by build | Media processing and inspection | Required |
| Ollama | https://github.com/ollama/ollama | MIT repository; model licence varies | Optional local LLM | Adapter included |
| faster-whisper | https://github.com/SYSTRAN/faster-whisper | MIT | Optional ASR and word timestamps | Adapter included |
| Whisper weights | https://huggingface.co/models?library=faster-whisper | Varies | ASR model | User reviews selected model |
| pytest | https://github.com/pytest-dev/pytest | MIT | Automated tests | Used |

## Operational and licensing notes

- FFmpeg obligations depend on the selected binary and enabled codecs; distribute its notices and comply with LGPL/GPL requirements.
- ASR models have separate weight licences, download sizes, language coverage, and CPU/GPU requirements.
- No music, stock media, logos, or fonts are bundled. Users are responsible for permissions.
- Ollama and ASR are local by default; no paid API key is required.
- Tamil caption rendering depends on installed fonts and glyph coverage; verify the chosen font before export.
