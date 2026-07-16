# Attribution

Parts of this package are derived from **oh-my-claudecode (OMC)** by Yeachan Heo,
used under the MIT License. ctxgit re-implements OMC's team-pipeline control core
in Python so it runs under ctxgit's own job engine (no OMC Node runtime required),
and vendors OMC's agent prompt library.

Derived from:

- `src/hooks/team-pipeline/types.ts`, `state.ts`, `transitions.ts`
  → `pipeline.py` (phases, allowed-transition table, entry guards, fix-loop bound,
  cancel/resume semantics)
- `skills/team/SKILL.md`
  → stage routing table, worker preamble, and handoff format used by `stages.py`
  and `protocol.py`
- `agents/*.md`
  → vendored agent prompt library under `agents/`

Upstream: https://github.com/Yeachan-Heo/oh-my-claudecode

---

MIT License

Copyright (c) 2025 Yeachan Heo

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
