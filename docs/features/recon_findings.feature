# Recon findings: the simple faults a crawl finds by rule, with no model.
#
# A browser reports HTTP status, console errors and exceptions, so a whole class of
# defects is caught by fixed rules. On EcoEstate this found, for free, that
# GET /api/property-prices returns 500 for every year. These functional oracles run on
# every capture. Graph oracles then judge the shape of the finished map: dead controls,
# blocked controls, redundant controls and dead ends. Those are observations, kept
# apart from the functional findings, because a "dead" control on a canvas app may
# have changed only pixels; they are labelled for what they are, not as defects.
# Gesture probes are skipped by the control oracles, since a wheel that moves nothing
# is not a dead control.
#
# Code: .experiments/web-recon/oracles.py, analyze.py, crawl.py (dedup_findings)

Feature: The crawler reports functional and structural problems
  As someone looking for obvious faults
  I want HTTP errors, failed requests, console errors and exceptions recorded, plus dead, blocked and redundant controls and dead ends
  So that recon already finds the simple problems before any model is involved

  Scenario Outline: Functional oracles turn a capture's evidence into findings
    # They run on the start page and on the page after every action, gestures included.
    # Third-party requests are kept too.
    Given a capture on state "st02" whose evidence includes <evidence>
    When the observation oracles run
    Then a finding of kind "<kind>" is recorded on "st02" with summary "<summary>"

    Examples:
      | evidence                                                                                  | kind           | summary                                                                          |
      | a GET to "http://127.0.0.1:3000/api/property-prices?year=2021" answered 500               | http_error     | 500 GET http://127.0.0.1:3000/api/property-prices?year=2021                      |
      | a GET to "http://127.0.0.1:3000/api/items" answered 404                                   | http_error     | 404 GET http://127.0.0.1:3000/api/items                                          |
      | a GET to "http://127.0.0.1:3000/api/items" that failed with "net::ERR_CONNECTION_REFUSED" | request_failed | request failed (net::ERR_CONNECTION_REFUSED) GET http://127.0.0.1:3000/api/items |
      | a console message of type "error" saying "Cannot read properties of undefined"            | console_error  | Cannot read properties of undefined                                              |
      | an uncaught page exception "TypeError: x is null"                                         | exception      | TypeError: x is null                                                             |

  Scenario Outline: Known dev noise in the console is ignored
    # Matched case-insensitively anywhere in the message text.
    Given a console error whose text contains "<text>"
    When the observation oracles run
    Then no finding is recorded for it

    Examples:
      | text                                                |
      | Content Security Policy directive 'frame-ancestors' |
      | Download the React DevTools                         |

  Scenario: One defect is reported once per state, however many visits fire it
    Given a state revisited 5 times, each visit firing the same 500
    When the crawl builds its ontology
    Then one "http_error" finding with that summary is kept for that state

  Scenario Outline: Graph oracles flag navigation anomalies over the finished map
    Given a finished ontology where <shape>
    When the graph oracles run
    Then an observation of kind "<kind>" is recorded on "st01" with summary "<summary>"

    Examples:
      | shape                                                                           | kind               | summary                                                     |
      | clicking "button:Refresh" on "st01" has effect "dead"                           | dead_control       | click button:Refresh on st01 changed nothing observable     |
      | clicking "button:Menu" on "st01" has effect "blocked"                           | blocked_control    | click button:Menu on st01 could not be actuated             |
      | "link:Home" and "link:Logo" on "st01" both navigate to "st02"                   | redundant_controls | 2 controls on st01 all lead to st02: link:Home, link:Logo   |
      | "st01" was acted on but has no navigation to another state and no external exit | dead_end           | st01 was explored but has no navigation onward - a dead end |

  Scenario Outline: Graph oracles leave out what isn't a real anomaly
    Given a finished ontology where <shape>
    When the graph oracles run
    Then no "<kind>" observation is recorded

    Examples:
      | shape                                                           | kind               |
      | a gesture probe "gesture:wheel down" has effect "dead"          | dead_control       |
      | a gesture probe could not be fired and has effect "blocked"     | blocked_control    |
      | two controls lead to the same state but with effect "changed"   | redundant_controls |
      | the same control navigates to the same state twice              | redundant_controls |
      | a state none of whose controls were tried within the budget     | dead_end           |
      | a state whose only exit is an off-site link (effect "external") | dead_end           |
      | the app has only one state                                      | dead_end           |

  Scenario: Findings and observations are kept apart in the ontology
    When the crawl builds its ontology
    Then functional findings are written under "findings"
    And graph observations (and any --resume drift) are written under "observations"
