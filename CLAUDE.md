# CLAUDE.md

## Project
Hackathon project for the USC Dual-Use InnovateLA Hackathon.
Track 02 — Energy, with Base Power: "On the Grid".

**The user we're building for:** the dispatcher of a home-battery fleet.

**The problem:** Homes full of automated batteries are part of the grid, and critical
services (harbor, phones, cold storage) run on it. When something strains or looks odd,
the blunt move is shedding load. We're building what sits between "normal" and "shed".

**Questions our solution should answer:**
- Whose power can wait, and how would the dispatcher know?
- When a battery goes silent: is it broken, tripped, or just not talking?
- How does the same battery earn its keep on an ordinary day?

## Priorities
- A working demo by judging beats a complete system. Favor simple, visible results.
- Use simulated/mock fleet data unless we get real data from Base Power.
- Keep the dispatcher (a human) in the loop for high-impact decisions.

## What we're building
A web dashboard for the dispatcher: shows the battery fleet, flags batteries that look
odd, and suggests what to do before anyone reaches for load shedding.

## Tech stack
- Python + Streamlit (web dashboard)
- Simulated battery fleet data (no real API), with planted problems for the demo:
  a battery that goes silent, one that trips, and a heat wave straining the grid
- Rules-based triage first; AI summaries for the dispatcher only if time allows
- I'm a beginner: explain what you're doing in plain language, keep the code simple,
  and tell me exactly what to type when I need to run something

## Commands
- Install: pip install -r requirements.txt
- Run: streamlit run app.py

## Structure
- app.py: the dashboard
- simulator.py: generates the fake fleet and planted problems
- rules.py: decides what's normal, what can wait, and what needs the dispatcher
- requirements.txt: list of Python packages to install

## Conventions
- Keep code readable for a two-person team working fast.
- Small commits with clear messages.
- Ask before adding large dependencies.
