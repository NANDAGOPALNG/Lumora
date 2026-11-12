"""Tests for the Jina Reranker API integration (app/retrieval/reranker.py).

All HTTP is mocked with httpx.MockTransport - no test needs a real Jina API
key or network access, and backoff sleeps are recorded, not waited for.
"""

import asyncio
import inspect
import json
import uuid

import app.retrieval.reranker as reranker_module
import httpx
import pytest
from app.retrieval.hybrid_retriever import HybridSearchResult
from app.retrieval.reranker import CrossEncoderReranker, RerankedResult, RerankerError
from app.retrieval.validation import RetrievalValidationError
from app.services.search_service import SearchService

SECRET_KEY = "jina_test_SECRET_key_123"


# --------------------------------------------------------------------------- helpers


class Recorder:
    """Records requests/sleeps and replays a scripted list of responses."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.sleeps = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        item = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(item, Exception):
            raise item
        return item


def jina_response(scores_by_index, *, order=None):
    """A Jina-shaped 200 response. `order` controls the response ordering."""
    indexes = order if order is not None else sorted(scores_by_index, key=lambda i: -scores_by_index[i])
    return httpx.Response(
        200,
        json={
            "model": "jina-reranker-v2-base-multilingual",
            "usage": {"total_tokens": 10},
            "results": [{"index": i, "relevance_score": scores_by_index[i]} for i in indexes],
        },
    )


@pytest.fixture(autouse=True)
def jina_env(monkeypatch):
    monkeypatch.setenv("JINA_API_KEY", SECRET_KEY)
    monkeypatch.delenv("JINA_RERANKER_URL", raising=False)
    monkeypatch.delenv("JINA_RERANKER_MODEL_NAME", raising=False)


@pytest.fixture
def mock_jina(monkeypatch):
    def install(*responses):
        recorder = Recorder(responses)
        monkeypatch.setattr(
            reranker_module,
            "_new_client",
            lambda: httpx.AsyncClient(transport=httpx.MockTransport(recorder.handler)),
        )

        async def fake_sleep(seconds):
            recorder.sleeps.append(seconds)

        monkeypatch.setattr(reranker_module, "_sleep", fake_sleep)
        return recorder

    return install


def candidate(content, *, n=0, chunk_id=None):
    return HybridSearchResult(
        chunk_id=chunk_id or uuid.UUID(int=n + 1),
        document_id=uuid.UUID(int=1000 + n),
        workspace_id=uuid.UUID(int=2000),
        filename=f"doc{n}.txt",
        chunk_index=n,
        source="txt",
        score=0.5,
        content=content,
    )


def rerank(candidates, query="annual leave", **kwargs):
    return asyncio.run(CrossEncoderReranker().rerank(query, candidates, **kwargs))


# --------------------------------------------------------------------------- success path


def test_successful_rerank_sends_documented_request(mock_jina):
    rec = mock_jina(jina_response({0: 0.1, 1: 0.9}))
    results = rerank([candidate("first", n=0), candidate("second", n=1)])

    assert [r.content for r in results] == ["second", "first"]
    assert len(rec.requests) == 1
    request = rec.requests[0]
    assert str(request.url) == "https://api.jina.ai/v1/rerank"
    assert request.headers["authorization"] == f"Bearer {SECRET_KEY}"
    body = json.loads(request.content)
    assert body == {
        "model": "jina-reranker-v2-base-multilingual",
        "query": "annual leave",
        "documents": ["first", "second"],
        "top_n": 2,
        "return_documents": False,
    }


def test_model_and_url_are_configurable(mock_jina, monkeypatch):
    monkeypatch.setenv("JINA_RERANKER_URL", "https://example.test/rerank")
    monkeypatch.setenv("JINA_RERANKER_MODEL_NAME", "some-other-model")
    rec = mock_jina(jina_response({0: 1.0}))
    rerank([candidate("only")])
    assert str(rec.requests[0].url) == "https://example.test/rerank"
    assert json.loads(rec.requests[0].content)["model"] == "some-other-model"


def test_scores_are_mapped_by_returned_index_not_response_position(mock_jina):
    # The API returns the best document first, regardless of input order.
    mock_jina(jina_response({0: 0.2, 1: 0.7, 2: 0.4}, order=[1, 2, 0]))
    results = rerank([candidate("a", n=0), candidate("b", n=1), candidate("c", n=2)])
    assert {r.content: r.score for r in results} == {"a": 0.2, "b": 0.7, "c": 0.4}


def test_results_are_sorted_by_descending_score(mock_jina):
    # Response deliberately in ascending order to prove local sorting.
    mock_jina(jina_response({0: 0.1, 1: 0.3, 2: 0.2}, order=[0, 2, 1]))
    results = rerank([candidate("a", n=0), candidate("b", n=1), candidate("c", n=2)])
    assert [r.content for r in results] == ["b", "c", "a"]
    assert [r.score for r in results] == [0.3, 0.2, 0.1]


def test_candidate_metadata_is_preserved(mock_jina):
    mock_jina(jina_response({0: 0.5}))
    original = candidate("hello world", n=7)
    (result,) = rerank([original])
    assert isinstance(result, RerankedResult)
    assert (result.chunk_id, result.document_id, result.workspace_id) == (
        original.chunk_id,
        original.document_id,
        original.workspace_id,
    )
    assert (result.filename, result.chunk_index, result.source, result.content) == (
        "doc7.txt",
        7,
        "txt",
        "hello world",
    )
    assert result.score == 0.5  # replaced by the reranker's score, not 0.5 hybrid by coincidence


def test_ties_break_deterministically_by_chunk_id(mock_jina):
    low, high = uuid.UUID(int=5), uuid.UUID(int=9)
    mock_jina(jina_response({0: 0.5, 1: 0.5}))
    results = rerank([candidate("x", n=0, chunk_id=high), candidate("y", n=1, chunk_id=low)])
    assert [r.chunk_id for r in results] == [low, high]


def test_top_k_truncates_locally_and_still_scores_everything(mock_jina):
    rec = mock_jina(jina_response({0: 0.1, 1: 0.9, 2: 0.5}))
    results = rerank([candidate("a", n=0), candidate("b", n=1), candidate("c", n=2)], top_k=2)
    assert [r.content for r in results] == ["b", "c"]
    # All candidates are scored so tie-breaking at the cut-off stays deterministic.
    assert json.loads(rec.requests[0].content)["top_n"] == 3


def test_top_k_larger_than_candidates_returns_all(mock_jina):
    mock_jina(jina_response({0: 0.1, 1: 0.9}))
    assert len(rerank([candidate("a", n=0), candidate("b", n=1)], top_k=50)) == 2


def test_invalid_query_and_top_k_are_rejected_before_any_request(mock_jina):
    rec = mock_jina(jina_response({0: 1.0}))
    with pytest.raises(RetrievalValidationError):
        rerank([candidate("a")], query="   ")
    with pytest.raises(RetrievalValidationError):
        rerank([candidate("a")], top_k=0)
    with pytest.raises(RerankerError):
        rerank("not-a-list")
    assert rec.requests == []


# --------------------------------------------------------------------------- empty / no-content


def test_empty_candidate_list_makes_no_request(mock_jina):
    rec = mock_jina(jina_response({}))
    assert rerank([]) == []
    assert rec.requests == []


def test_empty_candidate_list_does_not_need_an_api_key(mock_jina, monkeypatch):
    monkeypatch.setenv("JINA_API_KEY", "")
    assert rerank([]) == []


def test_missing_content_candidates_are_not_sent_and_rank_last_at_neg_inf(mock_jina):
    rec = mock_jina(jina_response({0: 0.4}))
    results = rerank([candidate(None, n=0), candidate("real", n=1)])
    assert json.loads(rec.requests[0].content)["documents"] == ["real"]
    assert [r.content for r in results] == ["real", None]
    assert results[1].score == float("-inf")
    assert results[1].filename == "doc0.txt"  # not silently discarded, metadata intact


def test_blank_content_candidates_are_not_sent_and_rank_last_at_neg_inf(mock_jina):
    rec = mock_jina(jina_response({0: -3.0}))  # even a negative score outranks -inf
    results = rerank([candidate("   \n\t", n=0), candidate("real", n=1)])
    assert json.loads(rec.requests[0].content)["documents"] == ["real"]
    assert [r.score for r in results] == [-3.0, float("-inf")]


def test_all_candidates_without_content_make_no_api_request(mock_jina, monkeypatch):
    rec = mock_jina(jina_response({}))
    monkeypatch.setenv("JINA_API_KEY", "")  # must not even require the key
    results = rerank([candidate(None, n=0), candidate("", n=1)])
    assert rec.requests == []
    assert len(results) == 2
    assert all(r.score == float("-inf") for r in results)
    assert [r.chunk_id for r in results] == sorted(r.chunk_id for r in results)


def test_top_k_applies_across_scored_and_unscored(mock_jina):
    mock_jina(jina_response({0: 0.9}))
    results = rerank([candidate(None, n=0), candidate("real", n=1), candidate(None, n=2)], top_k=2)
    assert len(results) == 2
    assert results[0].content == "real"


# --------------------------------------------------------------------------- auth / config


def test_missing_api_key_raises_without_request(mock_jina, monkeypatch):
    monkeypatch.setenv("JINA_API_KEY", "")
    rec = mock_jina(jina_response({0: 1.0}))
    with pytest.raises(RerankerError, match="JINA_API_KEY is not configured"):
        rerank([candidate("a")])
    assert rec.requests == []


@pytest.mark.parametrize("status", [401, 403])
def test_auth_failures_raise_without_retry_and_never_leak_key(mock_jina, status):
    rec = mock_jina(httpx.Response(status, json={"detail": f"bad key {SECRET_KEY}"}))
    with pytest.raises(RerankerError) as excinfo:
        rerank([candidate("a")])
    assert str(status) in str(excinfo.value)
    assert SECRET_KEY not in str(excinfo.value)
    assert len(rec.requests) == 1
    assert rec.sleeps == []


@pytest.mark.parametrize("status", [400, 404, 422])
def test_other_client_errors_are_permanent_and_not_retried(mock_jina, status):
    rec = mock_jina(httpx.Response(status, json={"detail": "nope"}))
    with pytest.raises(RerankerError, match=str(status)):
        rerank([candidate("a")])
    assert len(rec.requests) == 1
    assert rec.sleeps == []


# --------------------------------------------------------------------------- retries


def test_429_is_retried_with_exponential_backoff_then_succeeds(mock_jina):
    rec = mock_jina(httpx.Response(429), httpx.Response(429), jina_response({0: 0.8}))
    (result,) = rerank([candidate("a")])
    assert result.score == 0.8
    assert len(rec.requests) == 3
    assert rec.sleeps == [1.0, 2.0]


def test_persistent_429_is_bounded_and_raises(mock_jina):
    rec = mock_jina(httpx.Response(429))
    with pytest.raises(RerankerError, match="failed after all retries"):
        rerank([candidate("a")])
    assert len(rec.requests) == reranker_module._MAX_RETRIES
    assert rec.sleeps == [1.0, 2.0]  # no pointless sleep after the final attempt


@pytest.mark.parametrize("status", [500, 502, 503])
def test_5xx_is_retried_then_succeeds(mock_jina, status):
    rec = mock_jina(httpx.Response(status), jina_response({0: 0.3}))
    assert rerank([candidate("a")])[0].score == 0.3
    assert len(rec.requests) == 2
    assert rec.sleeps == [1.0]


def test_persistent_5xx_is_bounded_and_raises(mock_jina):
    rec = mock_jina(httpx.Response(503))
    with pytest.raises(RerankerError, match="failed after all retries"):
        rerank([candidate("a")])
    assert len(rec.requests) == reranker_module._MAX_RETRIES


# --------------------------------------------------------------------------- network


def test_timeout_raises_reranker_error(mock_jina):
    rec = mock_jina(httpx.ReadTimeout("slow"))
    with pytest.raises(RerankerError, match="timed out"):
        rerank([candidate("a")])
    assert len(rec.requests) == 1


def test_network_error_raises_safe_reranker_error(mock_jina):
    mock_jina(httpx.ConnectError(f"cannot connect to host with {SECRET_KEY}"))
    with pytest.raises(RerankerError) as excinfo:
        rerank([candidate("a")])
    assert "ConnectError" in str(excinfo.value)
    assert SECRET_KEY not in str(excinfo.value)  # only the exception type is surfaced


# --------------------------------------------------------------------------- malformed responses


def test_non_json_body_raises(mock_jina):
    mock_jina(httpx.Response(200, content=b"<html>gateway</html>"))
    with pytest.raises(RerankerError, match="malformed"):
        rerank([candidate("a")])


@pytest.mark.parametrize(
    "body",
    [
        [],  # not an object
        {},  # no results
        {"results": "nope"},  # results not a list
        {"results": [{"relevance_score": 0.5}]},  # no index
        {"results": [{"index": 0}]},  # no score
        {"results": ["x"]},  # item not an object
    ],
)
def test_missing_or_malformed_fields_raise(mock_jina, body):
    mock_jina(httpx.Response(200, json=body))
    with pytest.raises(RerankerError, match="missing required fields"):
        rerank([candidate("a")])


@pytest.mark.parametrize("bad_index", [-1, 2, 99, "0", 1.0, None, True])
def test_invalid_result_index_raises(mock_jina, bad_index):
    mock_jina(
        httpx.Response(
            200,
            json={"results": [{"index": bad_index, "relevance_score": 0.5}, {"index": 1, "relevance_score": 0.4}]},
        )
    )
    with pytest.raises(RerankerError):
        rerank([candidate("a", n=0), candidate("b", n=1)])


def test_duplicate_result_index_raises(mock_jina):
    mock_jina(
        httpx.Response(
            200,
            json={"results": [{"index": 0, "relevance_score": 0.9}, {"index": 0, "relevance_score": 0.8}]},
        )
    )
    with pytest.raises(RerankerError, match="duplicate"):
        rerank([candidate("a", n=0), candidate("b", n=1)])


def test_missing_candidate_in_response_raises_instead_of_dropping_it(mock_jina):
    mock_jina(jina_response({0: 0.9}))  # asked about 2 documents, scored 1
    with pytest.raises(RerankerError, match="1 results for 2 documents"):
        rerank([candidate("a", n=0), candidate("b", n=1)])


def test_extra_results_raise(mock_jina):
    mock_jina(jina_response({0: 0.9, 1: 0.8}))  # asked about 1 document
    with pytest.raises(RerankerError):
        rerank([candidate("a", n=0)])


@pytest.mark.parametrize("bad_score", ["0.5", None, True, float("nan"), float("inf"), float("-inf"), [0.5]])
def test_invalid_relevance_score_raises(mock_jina, bad_score):
    # json can't carry NaN/Infinity through httpx's strict encoder, so use raw content.
    payload = json.dumps({"results": [{"index": 0, "relevance_score": bad_score}]})
    mock_jina(httpx.Response(200, content=payload.encode(), headers={"content-type": "application/json"}))
    with pytest.raises(RerankerError, match="invalid relevance score"):
        rerank([candidate("a")])


# --------------------------------------------------------------------------- no local model


def test_no_local_model_machinery_remains():
    assert not hasattr(reranker_module, "_load_model")
    assert not hasattr(reranker_module, "_model")
    source = inspect.getsource(reranker_module)
    assert "sentence_transformers" not in source
    assert "CrossEncoder(" not in source
    assert "BAAI" not in source


def test_rerank_is_a_coroutine_function():
    assert inspect.iscoroutinefunction(CrossEncoderReranker.rerank)


# --------------------------------------------------------------------------- SearchService integration


class _StubQueryRewriter:
    def rewrite(self, query):
        class _Rewritten:
            normalized = query.strip().lower()

        return _Rewritten()


class _StubHybrid:
    def __init__(self, results):
        self.results = results
        self.calls = []

    async def search(self, query, workspace_id, *, document_id=None, top_k=5):
        self.calls.append((query, workspace_id, document_id, top_k))
        return self.results


class _StubContextBuilder:
    def __init__(self):
        self.built_from = None

    def build_context(self, results):
        self.built_from = results
        return "context"


class _AwaitRecordingReranker:
    """An async reranker that records that it was actually awaited."""

    def __init__(self):
        self.awaited = False
        self.args = None

    async def rerank(self, query, candidates, *, top_k=None):
        await asyncio.sleep(0)
        self.awaited = True
        self.args = (query, list(candidates), top_k)
        return ["reranked"]


def test_search_service_awaits_async_reranker():
    hybrid_results = [candidate("a", n=0)]
    reranker = _AwaitRecordingReranker()
    builder = _StubContextBuilder()
    service = SearchService(_StubQueryRewriter(), _StubHybrid(hybrid_results), reranker, builder)

    result = asyncio.run(service.search("  Annual Leave ", uuid.uuid4(), top_k=3))

    assert reranker.awaited is True
    assert reranker.args == ("annual leave", hybrid_results, 3)
    # The *result* of the awaited call (not a coroutine object) reaches the builder.
    assert builder.built_from == ["reranked"]
    assert result.context == "context"


def test_search_service_with_real_jina_reranker_end_to_end(mock_jina):
    rec = mock_jina(jina_response({0: 0.1, 1: 0.95}))
    hybrid = _StubHybrid([candidate("irrelevant", n=0), candidate("relevant", n=1), candidate(None, n=2)])
    builder = _StubContextBuilder()
    service = SearchService(_StubQueryRewriter(), hybrid, CrossEncoderReranker(), builder)

    asyncio.run(service.search("Annual Leave", uuid.uuid4(), top_k=5))

    assert [r.content for r in builder.built_from] == ["relevant", "irrelevant", None]
    assert json.loads(rec.requests[0].content)["query"] == "annual leave"


def test_slow_rerank_does_not_block_the_event_loop(monkeypatch):
    """The HTTP wait is awaited, so other tasks keep running during it."""

    async def slow_handler(request):
        await asyncio.sleep(0.4)
        return jina_response({0: 1.0})

    monkeypatch.setattr(
        reranker_module,
        "_new_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(slow_handler)),
    )

    async def scenario():
        ticks = 0
        done = asyncio.Event()

        async def ticker():
            nonlocal ticks
            while not done.is_set():
                await asyncio.sleep(0.02)
                ticks += 1

        task = asyncio.create_task(ticker())
        try:
            await CrossEncoderReranker().rerank("q", [candidate("a")])
        finally:
            done.set()
            await task
        return ticks

    assert asyncio.run(scenario()) >= 10
