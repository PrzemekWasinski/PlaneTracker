# PlaneTracker Refactor

## Goal

Restructure PlaneTracker into a maintainable production-style Python project without changing its intended aircraft-tracking behaviour.

The finished codebase should have clear module boundaries, smaller files, minimal duplication, no PlaneCam integration, and straightforward code that is easy to follow.

## Supported Environment

- Python 3
- Debian 13
- Dell OptiPlex 3050 SFF as the production machine
- Production launch through `scripts/plane_tracker.sh`
- GUI launchable directly in preview mode without importing or launching `plane_tracker.py`
- GUI preview must not require an SDR, antenna, readsb, network connection, or production backend
- GUI must render and frequently update live aircraft, trajectories, labels, statistics, and graphs, each plane should be updates exactly as a new adsb message gets processed

## Working Rules

- Preserve existing aircraft-tracking behaviour unless a task below explicitly removes it
- Make changes in small stages that can be tested independently
- Temporary breakage is acceptable on the working refactor branch
- Restore a runnable and testable application at the end of each completed phase
- Prefer descriptive names and simple control flow over compact or clever syntax
- Avoid dense list comprehensions when a normal loop is easier to read
- Extract repeated logic into well-named functions
- Keep related code together in focused packages
- Do not create broad dumping-ground modules such as `utils.py` or move a large file unchanged into a new folder
- Remove unused imports, variables, functions, modules, assets, configuration, and dependencies only after confirming they are unused
- Review Git history when it helps identify incomplete removals or the original purpose of unclear code
- Do not restore old features merely because they appear in Git history
- Keep each commit or implementation stage focused and reviewable

## Comment Style

Use short single-line comments only when they add useful context.

Required format:

```python
#Function to split an ADS-B message into a dictionary
```

Do not use:

- Comments that describe the development process or refer to previous requests
- Long or multi-line comments
- Comments with emojis
- Comment punctuation
- Docstrings used only as comments
- Comments that repeat what obvious code already says

Use docstrings only where they are necessary for a public API, documentation, or tooling.

## Phase 1: Establish a Baseline

- Document how to install and run the application
- Confirm the minimum supported Python 3 minor version available on Debian 13
- Record the current application startup path and main workflows
- Run the existing API and readsb test scripts separately and record their behaviour
- Add focused automated tests around important pure logic before moving it
- Define a quick manual GUI smoke test for behaviour that cannot be automated easily
- Record how to launch `modules/gui.py` in preview mode without radio hardware
- Record current configuration keys and runtime-created files or directories
- Plan and document a migration when YAML keys or file locations change

### Completion Criteria

- The current behaviour and known failures are documented
- Important refactors have a test or a repeatable manual check
- We can compare each later phase against the baseline

## Phase 2: Remove PlaneCam

Remove all PlaneCam-specific functionality, including:

- Camera host and port configuration
- Camera socket connections and communication protocol
- Camera reachability and connection-status checks
- Aircraft position messages sent to PlaneCam
- Manual and automatic camera tracking controls
- Camera capture queues, timers, state, and background threads
- Camera image receiving, decoding, metadata, history, and caching
- PlaneCam image directory creation and image saving
- Camera preview box, navigation controls, labels, and status display
- PlaneCam-only icons and other assets
- PlaneCam documentation in the README
- Imports and dependencies that become unused after removal

Do not remove unrelated image functionality. Radar maps, GUI icons, aircraft graphics, and user-triggered screenshots remain part of PlaneTracker unless separately approved.

### Completion Criteria

- Searching the active source, configuration, assets, and documentation finds no PlaneCam-specific code or wording
- The application does not open a connection to a camera service
- The GUI contains no camera preview or camera controls
- PlaneTracker still starts and displays aircraft data
- Existing non-camera functionality continues to work

## Phase 3: Create the Package Structure

Move the application from large scripts and generic modules into a proper Python package. Decide the final names after mapping current responsibilities, but aim for boundaries similar to:

```text
src/plane_tracker/
    __init__.py
    __main__.py
    app.py
    config/
    adsb/
    aircraft/
    history/
    services/
    gui/
        drawing/
        screens/
        widgets/
        assets.py
        colours.py
        fonts.py
        state.py
tests/
scripts/
config/
```

This tree is a direction, not a requirement to create empty folders. Every package should have one clear responsibility and should exist only when there is code that belongs in it.

Break up the current large files by responsibility, especially:

- `plane_tracker.py`
- `modules/gui.py`
- `modules/data_utils.py`
- `flight_history/stats.py`
- `modules/ui_utils.py`

### Completion Criteria

- The application has one clear entry point
- `scripts/plane_tracker.sh` remains the supported production launcher and is updated for the new entry point
- The GUI is separated from `plane_tracker.py` and does not import application globals from it
- Shared data is passed to the GUI through explicit models and interfaces
- The GUI has its own direct preview entry point with local sample data
- Standalone GUI preview works on development machines without SDR hardware or the production backend
- Business logic does not depend directly on Pygame rendering details
- Configuration loading, ADS-B data handling, aircraft state, history, external services, and GUI code have clear boundaries
- File and module names describe their responsibilities
- Imports work without modifying `sys.path`
- No large file remains solely because unrelated responsibilities are mixed together

## Phase 4: Simplify and Deduplicate

- Find repeated parsing, validation, formatting, drawing, and state-update logic
- Extract repeated behaviour into focused functions or classes
- Replace unnecessary global state with explicit state models where that improves clarity
- Reduce deeply nested conditionals with clearly named helper functions and early returns
- Consolidate duplicated constants and configuration defaults
- Use standard-library or existing project functionality instead of maintaining duplicate implementations
- Keep code explicit when a shorter expression would be harder to understand

### Completion Criteria

- Repeated logic has one clear implementation
- Functions have focused responsibilities and descriptive names
- Dependencies and state changes are visible through explicit interfaces
- Simplification does not change intended behaviour

## Phase 5: Remove Dead Code

- Use repository-wide reference searches and tests to identify unused code
- Review Git history for features that were removed incompletely
- Remove obsolete compatibility paths, stale configuration keys, unused assets, and unused dependencies
- Check startup scripts, tests, documentation, and deployment files before deleting apparently unused code
- Do not remove dynamically referenced GUI callbacks or assets based only on static-analysis output

### Completion Criteria

- Static checks report no unused imports or variables
- Requirements contain only runtime or development dependencies that are still needed
- Configuration examples contain only supported settings
- Deleted functionality has no remaining callers, assets, documentation, or generated directories

## Phase 6: Replace Pygame With PySide6

Rebuild the GUI with PySide6 and Qt Quick/QML. Keep the existing Pygame GUI available during development until the replacement has feature parity.

- Separate Python application state and services from the QML presentation layer
- Define explicit models and signals for passing aircraft, history, status, filter, and selection data to the GUI
- Apply aircraft updates incrementally without rebuilding the complete scene or aircraft model
- Update aircraft positions, headings, labels, selection states, and trajectories as new ADS-B data arrives
- Keep movement visually smooth between data updates where interpolation is appropriate
- Update graphs and statistics continuously without blocking aircraft rendering or user input
- Move data fetching, parsing, history processing, and other blocking work away from the GUI thread
- Batch or limit expensive visual updates where necessary without dropping source aircraft data
- Recreate every non-PlaneCam screen, control, graph, radar element, and interaction
- Use responsive layouts instead of fixed coordinates for one screen resolution
- Render at the display's native resolution with Qt high-DPI support
- Replace raster aircraft and toolbar icons with SVG assets where suitable
- Draw radar primitives, trajectories, labels, and selection states at native resolution
- Keep bitmap assets at sufficient source resolution and provide high-DPI variants where needed
- Preserve the existing colour meanings, aircraft rarity states, controls, filters, and workflows
- Provide realistic local sample data through the standalone GUI preview entry point
- Make preview data animate aircraft and update trajectories, graphs, statistics, and status values continuously
- Test the GUI at the production display resolution and at common development resolutions
- Test with at least the maximum aircraft count and update frequency observed in production
- Remove Pygame and its obsolete assets only after the PySide6 GUI reaches feature parity

### Completion Criteria

- Aircraft icons, text, radar lines, maps, and controls appear sharp at native resolution
- Resizing or using a high-DPI display does not make the interface pixelated or distort its layout
- Live aircraft move and rotate smoothly while trajectories, labels, statistics, and graphs continue updating
- Incoming aircraft data is not lost when rendering is busy
- The interface remains responsive under the maximum observed production aircraft load
- The PySide6 GUI provides every retained feature of the Pygame GUI
- The GUI runs standalone without importing or starting the production backend
- The full application launches the same GUI through `scripts/plane_tracker.sh`
- Pygame is removed from runtime dependencies after migration is complete

## Phase 7: Quality Pass

- Convert the separate API and readsb test scripts into pytest tests
- Keep hardware-dependent or live-network tests clearly marked so they can be run separately
- Add pytest tests for the new module boundaries
- Add a test or repeatable smoke check for standalone GUI preview mode
- Apply an agreed formatter and lint configuration if approved
- Run all automated tests and the GUI smoke test
- Update the README with the new installation, configuration, and launch instructions
- Verify operation on Debian 13 and the target device
- Review comments against the required style

### Completion Criteria

- The documented setup works from a clean checkout
- Tests and static checks pass
- The GUI starts and the main aircraft-tracking workflows work
- No PlaneCam functionality remains
- The repository structure and naming make each major responsibility easy to locate

## Phase 8: Design and Migrate Local Flight Storage

Start this phase only after the code reorganisation and PySide6 GUI migration are complete and stable.

- Document every CSV file, its fields, writers, readers, retention rules, and statistics derived from it
- Define the aircraft, observation, flight, position-history, and aggregate data that need persistent storage
- Evaluate local PostgreSQL against simpler local database options before making the final choice
- Prefer PostgreSQL if its querying, retention, concurrency, and maintenance benefits justify running a local database service
- Design a versioned schema with indexes suited to time-based aircraft and flight-history queries
- Put persistence behind repository interfaces so application and GUI code do not depend directly on PostgreSQL
- Create migrations for schema changes
- Build an importer that validates and preserves existing CSV history
- Switch reads and writes only after comparing database results with the existing CSV behaviour
- Define backup, restore, retention, and database-health procedures for the production machine
- Retain CSV export if it remains useful for portability or manual analysis
- Remove CSV runtime storage only after the database migration is verified

### Completion Criteria

- The selected database and its operational tradeoffs are documented
- Existing flight history migrates without silent data loss
- Stored results and statistics match the previous CSV implementation
- Database access does not block live aircraft processing or GUI updates
- A failed database write is logged and does not crash live tracking
- Setup, migration, backup, restore, and recovery are documented for Debian 13
- Obsolete CSV storage code is removed after successful migration

## Confirmed Decisions

- Support Python 3 on Debian 13
- Keep YAML configuration, but allow its structure and location to change when that improves maintainability
- Document migration steps for existing personal YAML configuration when it changes
- Add pytest and convert the existing standalone test scripts into pytest tests
- Add `ruff` as a development dependency for linting and formatting
- Replace Pygame with PySide6 and Qt Quick/QML
- Target a sharp, responsive, high-DPI GUI using vector assets where suitable
- Keep the Pygame GUI only until the PySide6 replacement reaches feature parity
- Preserve `scripts/plane_tracker.sh` as the normal way to launch the full application
- Separate the GUI from `plane_tracker.py`
- Preserve direct standalone GUI preview without SDR hardware or the production backend
- Use docstrings only where necessary
- A `src/plane_tracker/` package layout is acceptable
- Temporary breakage is acceptable while a refactor phase is in progress
- Preserve every non-PlaneCam feature and its intended behaviour
- Consider replacing CSV flight storage with a local PostgreSQL database only after the refactor and GUI migration are complete
