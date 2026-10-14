# FIRST_WEEK.md: a first week with the framework

An order in which to read and do things, using only what the other documents already say. Each line names the section to
open. Nothing here is a schedule; it is a sequence.

1. **Understand it.** [README.md](../README.md) (what it is and the documents table), then
   [ARCHITECTURE.md](ARCHITECTURE.md) and [GLOSSARY.md](GLOSSARY.md). Skim [KNOWN_ISSUES.md](KNOWN_ISSUES.md) so that
   nothing in it is a surprise later.
2. **Install it.** [INSTALL.md](INSTALL.md) sections 1 to 3, then **sections 4 to 6, "Configure secrets"**: where `.env`
   lives, every variable, the GitHub token and its scopes, one LLM provider and a spending limit, and how
   `python -m scripts.doctor` confirms it. Then section 9 (check the machine) and run the suite.
3. **Start from an empty database.** [OPERATIONS.md](OPERATIONS.md) **section 19**: the schema, the roster, `seed_data`,
   adding a student.
4. **Give a test student something to do.** [OPERATIONS.md](OPERATIONS.md) **section 20**: publish the first attempt (it
   invites nobody), deliver the next attempt, record it with `roster_apply`. Use a second GitHub account you control.
5. **Change an exercise safely.** [AUTHORING.md](AUTHORING.md) **section 10, "Change an existing assignment"**: what a
   changed master does to `master_version`, to the gap line ranges and to attempts in progress, and the commands to rerun.
   Then [HOWTO_EXTEND.md](HOWTO_EXTEND.md) for a new project, gap, check, agent or variable.
6. **Know what is proven.** [VALIDATION.md](VALIDATION.md), then [ROADMAP.md](ROADMAP.md) for what comes next and
   [DATA_PROTECTION.md](DATA_PROTECTION.md) before real students use it.
