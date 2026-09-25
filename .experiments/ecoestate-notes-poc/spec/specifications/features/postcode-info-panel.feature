@panel @ui @prices @walking
Feature: Postcode Information Panel
  As a user interested in a specific postcode
  I want to see detailed information in a side panel
  So that I can understand property prices and accessibility for that area

  Background:
    Given the application is loaded
    And postcode boundaries are displayed on the map

  # =============================================================================
  # Rule: Clicking a postcode opens the info panel
  # =============================================================================

  Rule: Clicking a postcode opens the info panel

    Scenario: Click on postcode opens info panel
      Given no info panel is currently displayed
      When I click on postcode "00180" on the map
      Then the info panel should appear on the right side of the screen
      And the panel should display information for postcode "00180"

    Scenario: Clicking a different postcode updates the panel
      Given the info panel is showing data for "00180"
      When I click on postcode "00100" on the map
      Then the panel should update to show information for "00100"
      And the previous postcode data should no longer be visible

    Scenario: Info panel does not interfere with map interaction
      Given the info panel is open
      When I pan or zoom the map
      Then the map should respond normally
      And the info panel should remain visible

  # =============================================================================
  # Rule: Info panel displays postcode location information
  # =============================================================================

  Rule: Info panel displays postcode location information

    Scenario: Panel header shows postcode number
      Given I click on postcode "00180"
      When the info panel opens
      Then the header should prominently display "00180"
      And a close button (×) should be visible in the header

    Scenario: Panel shows district and municipality names
      Given I click on a postcode in the Kamppi district
      When the info panel opens
      Then I should see a "Location" section
      And it should display the district name (e.g., "Kamppi, Helsinki")
      And it should display the municipality name

  # =============================================================================
  # Rule: Info panel displays property prices for the selected year
  # =============================================================================

  Rule: Info panel displays property prices for the selected year

    Scenario: Panel shows property prices section
      Given I am viewing the heatmap for year 2023
      When I click on a postcode with price data
      Then the info panel should show a "Property Prices" section
      And it should indicate the data year (2023)

    Scenario: Panel shows apartment prices
      Given the info panel is open for a postcode with apartment data
      Then I should see "Kerrostalo" (apartment) with a price in €/m²
      And the price should be the average of 1-room, 2-room, and 3+ room apartments

    Scenario: Panel shows row house prices
      Given the info panel is open for a postcode with row house data
      Then I should see "Rivitalo" (row house) with a price in €/m²

    Scenario: Panel shows N/A for missing price data
      Given the info panel is open for a postcode
      When row house data is not available for that postcode
      Then the row house price should display "N/A"

    Scenario Outline: Price format is consistent
      Given the info panel shows a price of <raw_price>
      Then it should be displayed as "<formatted_price>"

      Examples:
        | raw_price | formatted_price |
        | 4500      | 4,500 €/m²      |
        | 12000     | 12,000 €/m²     |
        | null      | N/A             |

  # =============================================================================
  # Rule: Info panel displays walking distance to services
  # =============================================================================

  Rule: Info panel displays walking distance to services

    Scenario: Walking distance section shows loading state initially
      When I click on a postcode
      And the info panel opens
      Then the "Walking Distance to Services" section should show "Loading..."

    Scenario: Walking distance updates after data loads
      Given the info panel is open and loading walking distance
      When the walking distance data loads
      Then the loading indicator should be replaced with the actual category

    Scenario Outline: Walking distance category is displayed with appropriate styling
      Given the walking distance for the postcode is "<category>"
      Then the walking distance should show "<display_text>"
      And the styling should indicate "<accessibility_level>"

      Examples:
        | category | display_text    | accessibility_level |
        | 5min     | < 5 min walk   | Excellent (green)   |
        | 10min    | 5-10 min walk  | Good (light green)  |
        | 15min    | 10-15 min walk | Moderate (yellow)   |
        | null     | > 15 min walk  | Far (gray)          |

    Scenario: Walking distance shows walking emoji
      Given the info panel is displaying walking distance
      Then a walking person emoji (🚶) should be visible

  # =============================================================================
  # Rule: Info panel shows data source attribution
  # =============================================================================

  Rule: Info panel shows data source attribution

    Scenario: Footer shows data sources
      Given the info panel is open
      Then the footer should display "Data: Statistics Finland, HSY"

  # =============================================================================
  # Rule: Info panel can be closed by user action
  # =============================================================================

  Rule: Info panel can be closed by user action

    Scenario: Close panel with X button
      Given the info panel is open
      When I click the close button (×)
      Then the info panel should close
      And the map should be fully visible

    Scenario: Close panel with Escape key
      Given the info panel is open
      When I press the Escape key
      Then the info panel should close

    Scenario: Clicking empty map area does not close panel
      Given the info panel is open
      When I click on an area of the map without postcode boundaries
      Then the info panel should remain open

  # =============================================================================
  # Rule: Info panel position and styling
  # =============================================================================

  Rule: Info panel position and styling

    Scenario: Panel appears on the right side
      Given I click on a postcode
      When the info panel opens
      Then the panel should be positioned on the right side of the screen
      And it should overlay part of the map

    Scenario: Panel has readable styling
      Given the info panel is open
      Then the panel should have a contrasting background
      And text should be clearly readable
      And sections should be visually separated

  # =============================================================================
  # Rule: Info panel contains a Notes section for personal annotations
  # =============================================================================

  Rule: Info panel contains a Notes section for personal annotations

    Scenario: Notes section is visible in the info panel
      Given the info panel is open for postcode "00180"
      Then a "Notes" heading should be visible inside the panel
      And a textarea with placeholder "Add a note about this postcode..." should be visible
      And an "Add Note" button should be visible

    Scenario: Notes section shows loading state while fetching
      Given I click on postcode "00180"
      When the info panel opens and notes are being fetched
      Then the notes section should display "Loading notes..."

    Scenario: Notes section shows empty state when no notes exist
      Given the info panel is open for "00180"
      And there are no notes for "00180"
      Then the notes section should display "No notes yet for this postcode."

    Scenario: Adding a new note
      Given the info panel is open for "00180"
      And I type "Good transport links" into the note textarea
      When I click the "Add Note" button
      Then "Good transport links" should appear in the notes list
      And the textarea should be cleared

    Scenario: Add Note button is disabled when textarea is empty
      Given the info panel is open for "00180"
      And the note textarea is empty
      Then the "Add Note" button should be disabled

    Scenario: Add Note button is disabled when textarea contains only whitespace
      Given the info panel is open for "00180"
      And the note textarea contains only spaces
      Then the "Add Note" button should be disabled

    Scenario: Editing an existing note
      Given the info panel is open for "00180"
      And a note "Good transport links" exists
      When I click the "Edit" button on that note
      Then an edit textarea should appear pre-filled with "Good transport links"
      And "Save" and "Cancel" buttons should be visible

    Scenario: Saving an edited note
      Given I am editing a note with content "Good transport links"
      When I change the text to "Excellent transport links"
      And I click "Save"
      Then the note should display "Excellent transport links"
      And the edit textarea should be dismissed

    Scenario: Cancelling an edit discards changes
      Given I am editing a note with content "Good transport links"
      When I change the text to "Something else"
      And I click "Cancel"
      Then the note should still display "Good transport links"
      And the edit textarea should be dismissed

    Scenario: Deleting a note
      Given the info panel is open for "00180"
      And a note "Good transport links" exists
      When I click the "Delete" button on that note
      Then "Good transport links" should be removed from the notes list

    Scenario: Note textarea enforces 500-character maximum
      Given the info panel is open for "00180"
      When I type more than 500 characters into the note textarea
      Then the textarea should not accept characters beyond 500
      And the character counter should show "500/500"

    Scenario: Character counter updates as user types
      Given the info panel is open for "00180"
      When I type "Hello" into the note textarea
      Then the character counter should show "5/500"

    Scenario: Notes are fetched fresh when a different postcode is selected
      Given I previously viewed notes for "00180"
      When I click on postcode "00100"
      Then the notes section should show "Loading notes..." briefly
      And the notes for "00100" should be displayed after loading

    Scenario: Error state is shown when notes cannot be fetched
      Given the notes API is unavailable
      When I open the info panel for "00180"
      Then the notes section should display an error message
