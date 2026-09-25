"""Minimal mock backend for the Playwright-MCP GUI PoC.

Deliberately trivial - the point of this SUT isn't its own logic (there
isn't any worth testing), it's proving a Driver can navigate a real
browser via Playwright MCP tools, click a button, and observe the result.
One endpoint: POST /answer, echoing back a canned sentence per choice.

Run with: uvicorn sut:app --port 8010
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI()

# The Vite dev server runs on a different port (frontend, JS) than this
# backend (Python) - the browser enforces CORS across that origin boundary,
# so it must be explicitly allowed here. Wide open (any origin) since this
# is a local-only throwaway PoC, not anything deployed.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class AnswerRequest(BaseModel):
    choice: str  # "yes" | "no"


@app.post("/answer")
def answer(request: AnswerRequest) -> dict:
    if request.choice == "yes":
        return {"text": "This is a test."}
    if request.choice == "no":
        return {"text": "This isn't a test."}
    return {"text": f"Unrecognized choice: {request.choice!r}"}
