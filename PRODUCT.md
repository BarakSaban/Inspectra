# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Two roles share one product.

- **Managers (admin):** run a team of fare inspectors for a public-transport operation. They work at a desk, mostly on a desktop monitor, with the live map and the team open for a whole shift; sometimes they check from a phone. Their job: see who is working now, send the right inspector to the right bus, notice what needs attention, and review how the team is doing over time.
- **Inspectors (field):** ride and stand at bus stops, using a phone, often outdoors and in a hurry. Their screens are mobile-first and out of scope for desktop work.

Hebrew is the default language, with English, Arabic and Russian; right-to-left layout is first class.

## Product Purpose

Inspectra tells managers where fare evasion is likely and gets inspectors onto buses they can actually catch. It combines the static timetable (GTFS) with live bus positions (SIRI), recommends a bus and stop for each inspector, tracks shifts, breaks and results, and shows the manager the whole team live. Success: the manager spends their time deciding, not hunting for information, and inspectors spend theirs on buses.

## Positioning

Assignments are computed from real arrival times plus the inspector's walking time to the stop, not from a fixed schedule or a guess.

## Operating Context

Managers open it at the start of a shift and leave it running. Accounts are created by sign-up: a manager gets a code, inspectors register with that code. Data is real only; demo accounts can be created and removed with `tools/demo_data.py`.

## Capabilities and Constraints

- Live map of the team with states (available, offered, on a ride, on break, offline); assignment and cancel; bulk online/offline; team settings (safety buffer, search radius, max walk, longest break); audit log.
- Per-inspector stats over day, week, month, year; analytics with date presets, hotspots, rankings, hours and break time per inspector.
- Flask, SQLite, server-rendered templates, vanilla JavaScript, Leaflet maps, Chart.js on analytics; Font Awesome icons.
- Four languages with RTL; dark theme on manager pages.
- Terminology: inspectors are called "פקחים" in Hebrew.

## Brand Commitments

- Name: Inspectra. The hexagon-eye mark and wordmark in blue (`app/static/img/inspectra-logo.png`, `inspectra-mark.png`) stay.
- The user asked for a refined, clearly more beautiful version of the current blue identity, not a new colour world.

## Evidence on Hand

Real SIRI and GTFS data, a working app with demo accounts (`demo.manager1`, password in README). No testimonials, customers or marketing claims exist and none may be invented.

## Product Principles

1. The live picture first: what is happening now outranks history.
2. Exceptions over numbers: surface what needs attention rather than more charts.
3. Real data only; never fake a state.
4. Desktop-first for managers, mobile-first for inspectors, both always usable.
5. Every language is first class, including right-to-left.

## Accessibility & Inclusion

Right-to-left support, readable contrast in light and dark, keyboard focus visible, touch targets of 44px on phones.
