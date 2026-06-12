"""M5 message generation: a well-structured cold email + LinkedIn note for a job.

The LLM produces the *tailored content* (intro, requirement-aligned bullets,
project highlight, closing). We assemble the final email in code so the
formatting and the contact footer are always correct and consistent.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from . import config, llm
from .profile import Profile

DESC_LIMIT = 2500


class Outreach(BaseModel):
    subject: str = Field(description="concise, specific subject, e.g. 'Application for <role> at <company>'")
    hook: str = Field(
        description="ONE short clause saying what about THIS role aligns / why "
        "reaching out — e.g. 'the stack and BFSI domain both align with what I've "
        "been building'. No 'Came across...' prefix, no leading capital needed, "
        "no trailing period."
    )
    intro: str = Field(
        description="2-4 sentence PURE self-introduction: 'I'm <name>, a <seniority> "
        "with <X> years in <key skills>' + a flagship project with quantified "
        "results. Do NOT name the target role/company (that's stated separately). "
        "No greeting, no placeholders."
    )
    alignment_points: list[str] = Field(
        description="5-8 bullets, each 'Skill/Area — concrete how-I-used-it', "
        "mapped to THIS job's stated requirements. No leading bullet char."
    )
    highlight: str = Field(
        default="",
        description="optional ONE sentence about a standout project (e.g. the "
        "React Flow / NestJS workflow builder). Empty string if not relevant.",
    )
    leveling_up: str = Field(
        default="",
        description="optional: ONE skill/area the JD asks for that the candidate is "
        "still growing into, as the area ONLY (e.g. 'AWS'). Empty string if the "
        "candidate already covers the requirements.",
    )
    closing: str = Field(
        description="1-2 sentences: genuine interest in this specific company/role "
        "+ availability (e.g. immediate joiner). No sign-off, no contact info."
    )


SYSTEM = (
    "You are the job candidate writing tailored outreach (a cold email AND a "
    "LinkedIn message) for ONE specific role. Produce structured content: a one-line "
    "'hook' on what about this role aligns; a PURE self-introduction (who the "
    "candidate is + a flagship project with quantified results, WITHOUT naming the "
    "target role/company); requirement-aligned bullets mapping the candidate's REAL "
    "skills to the job's stated requirements; an optional standout-project highlight; "
    "optionally ONE area the candidate is still leveling up on (only if the JD needs "
    "it and the candidate is light there); and a closing. "
    "Be specific and truthful to the candidate's background — never invent skills or "
    "use bracketed placeholders. Do NOT include greetings, sign-offs, or contact "
    "details; those are added separately."
)


def generate(profile: Profile, job: dict, contact: dict | None) -> Outreach:
    desc = (job.get("description") or "")[:DESC_LIMIT]
    prompt = (
        f"CANDIDATE: {profile.name}\n"
        f"- Seniority: {profile.seniority} (~{profile.total_years_experience} yrs)\n"
        f"- Skills: {', '.join(profile.skills)}\n"
        f"- Summary: {profile.summary}\n"
        f"- Recent role highlights: "
        + " | ".join(
            f"{r.title} @ {r.company}: " + "; ".join(r.highlights)
            for r in profile.roles[:2]
        )
        + f"\n\nJOB\n- Title: {job.get('title')}\n- Company: {job.get('company')}\n"
        f"- Location: {job.get('location')}\n- Description: {desc}\n\n"
        "Write the application content for THIS role, aligning bullets to its "
        "requirements."
    )
    return llm.generate_structured(prompt, Outreach, system=SYSTEM, verbose=False)


def _first_name(name: str) -> str:
    return (name or "").split()[0] if name and name.split() else ""


def _url(u: str) -> str:
    """Ensure a link has a scheme (profile stores bare domains like github.com/x)."""
    u = (u or "").strip()
    if u and not u.startswith(("http://", "https://")):
        u = "https://" + u
    return u


def _resume_url() -> str:
    return (config.get("RESUME_URL") or "").strip()


def _contact_footer(p: Profile) -> str:
    lines = []
    if p.portfolio:
        lines.append(f"📋 Portfolio: {p.portfolio}")
    if p.github:
        lines.append(f"💻 GitHub: {p.github}")
    contact_line = " | ".join(
        x for x in [f"📧 {p.email}" if p.email else "", f"📞 {p.phone}" if p.phone else ""]
        if x
    )
    if contact_line:
        lines.append(contact_line)
    return "\n".join(lines)


def render_email(profile: Profile, job: dict, contact: dict | None, o: Outreach) -> str:
    """Assemble the final, formatted email body from the LLM content + footer."""
    first = _first_name((contact or {}).get("name") or "")
    greeting = f"Hi {first}," if first else "Hi Hiring Team,"
    bullets = "\n".join(f"• {b.lstrip('•- ').strip()}" for b in o.alignment_points)

    blocks = [
        greeting,
        o.intro.strip(),
        "How I align with your requirements:\n\n" + bullets,
    ]
    if o.highlight.strip():
        blocks.append(o.highlight.strip())
    blocks.append(o.closing.strip())

    footer = _contact_footer(profile)
    if footer:
        blocks.append(footer)
    blocks.append("Resume attached. Looking forward to connecting!")
    blocks.append(f"Best regards,\n{profile.name}")
    return "\n\n".join(blocks)


def render_linkedin(profile: Profile, job: dict, contact: dict | None, o: Outreach) -> str:
    """Assemble the full LinkedIn outreach MESSAGE (not a 300-char connect note).

    Job ID is included only when the portal exposed one; otherwise the opener
    stays generic.
    """
    first = _first_name((contact or {}).get("name") or "")
    greeting = f"Hi {first}," if first else "Hi there,"

    title = job.get("title") or "the role"
    company = job.get("company") or "your company"
    jid = (job.get("external_id") or "").strip()
    job_id_part = f" (Job ID: {jid})" if jid else ""
    opener = (f"Came across the {title} opening at {company}{job_id_part} "
              "and wanted to reach out directly")
    hook = o.hook.strip().rstrip(".")
    opener += f" — {hook}." if hook else "."

    bullets = "\n".join(f"• {b.lstrip('•- ').strip()}" for b in o.alignment_points)

    blocks = [greeting, opener, o.intro.strip(), "What lines up well:\n" + bullets]
    if o.leveling_up.strip():
        area = o.leveling_up.strip().rstrip(".")
        blocks.append(f"{area} is an area I'm actively leveling up on.")
    blocks.append("Would love to connect or get referred if you think I'd be a good fit.")

    sig = [profile.name]
    links = " | ".join(x for x in [
        profile.email, _url(profile.portfolio), _url(profile.github)] if x)
    if links:
        sig.append(links)
    if _resume_url():
        sig.append(f"Resume: {_resume_url()}")
    blocks.append("\n".join(sig))

    return "\n\n".join(blocks)


def draft(profile: Profile, job: dict, contact: dict | None) -> dict:
    """Convenience: generate + render → {subject, body, linkedin}."""
    o = generate(profile, job, contact)
    return {
        "subject": o.subject,
        "body": render_email(profile, job, contact, o),
        "linkedin": render_linkedin(profile, job, contact, o),
    }
