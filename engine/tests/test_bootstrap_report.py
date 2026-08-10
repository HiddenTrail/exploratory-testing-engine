"""engine.bootstrap.report.render_discovery_report - the --discover-only
counterpart to engine.report's full checkpoint-loop report. Pure string
rendering, no network/LLM calls."""

from engine.bootstrap.discovery import DiscoveredEndpoint, DiscoveredField, DiscoveredSchema
from engine.bootstrap.report import render_discovery_report


def test_found_schema_renders_endpoint_and_fields_without_double_escaping():
    schema = DiscoveredSchema(
        status="found", fetched_from="/openapi.json", source="openapi", confirmed=True,
        endpoints=[
            DiscoveredEndpoint(
                path="/submit", method="POST",
                request_fields=[
                    DiscoveredField(name="client_id", type="string", required=True, description="identifies the caller"),
                    DiscoveredField(name="priority", type="string", required=False, enum=["normal", "high"]),
                ],
                response_fields=[], raw_request_schema={}, raw_response_schema={},
            )
        ],
    )

    html = render_discovery_report(schema, "http://test")

    assert "POST /submit" in html
    assert "client_id" in html and "identifies the caller" in html
    assert "priority" in html
    assert "&lt;span" not in html  # the double-escaping bug: badge markup must never appear literal
    assert '<span class="badge badge-good">found</span>' in html
    assert html.count('<span class="badge badge-good">required</span>') == 1
    assert html.count('<span class="badge badge-bad">optional</span>') == 1


def test_not_found_schema_has_no_endpoints_section_content_but_still_renders():
    schema = DiscoveredSchema(status="not_found", fetched_from=None)

    html = render_discovery_report(schema, "http://test")

    assert '<span class="badge badge-warn">not_found</span>' in html
    assert "No endpoints discovered" in html


def test_malformed_schema_renders_error_section():
    schema = DiscoveredSchema(status="malformed", fetched_from="/openapi.json", error="unsupported $ref 'foo'")

    html = render_discovery_report(schema, "http://test")

    assert '<span class="badge badge-bad">malformed</span>' in html
    assert "unsupported $ref" in html
    assert '<a href="#error">Error</a>' in html


def test_notes_render_as_prose_when_present():
    schema = DiscoveredSchema(
        status="found", fetched_from=None, source="freetext", confirmed=False,
        notes="still unsure whether priority actually does anything",
        endpoints=[
            DiscoveredEndpoint(path="/x", method="POST", request_fields=[], response_fields=[], raw_request_schema={}, raw_response_schema={}),
        ],
    )

    html = render_discovery_report(schema, "http://test")

    assert "still unsure whether priority actually does anything" in html
    assert '<a href="#notes">Notes</a>' in html


def test_base_url_and_confirmed_flag_are_escaped_and_shown():
    schema = DiscoveredSchema(status="found", fetched_from=None, confirmed=False, endpoints=[
        DiscoveredEndpoint(path="/x", method="GET", request_fields=[], response_fields=[], raw_request_schema={}, raw_response_schema={}),
    ])

    html = render_discovery_report(schema, "http://evil.example/<script>")

    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert '<span class="num">no</span>' in html
