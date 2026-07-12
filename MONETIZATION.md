# Monetizing autobot — an honest assessment

The questions you asked: *Should this be a tiny subscription (~$1/mo)? Won't people just
reverse engineer it? Or release it free as a portfolio project? Does a closed-source
subscription impress hiring managers?*

## The reality check

**Yes, anything that runs on the user's machine can be copied.** This tool is a few
hundred lines of Python gluing Notion's public API to CLIs the user already owns. There
is no secret sauce to protect — obfuscation would only make it worse to use. The moat for
a tool like this is never the code; it's either **hosting convenience** (they pay so they
don't have to run it) or **distribution/trust** (they found yours first and it works).

**The $1/month math doesn't work.** Stripe charges ~$0.30 + 2.9% per transaction — about
33¢ of every $1, before taxes, chargebacks, or a single support email. Micro-subscriptions
also *signal* low value; people are more skeptical of a $1/mo tool than a $5/mo one. The
realistic floor for a subscription is $3–5/mo, and annual billing ($10–20/yr) is better
still at this scale.

**A closed-source $1/mo service is the weakest portfolio play.** Hiring managers can't
read closed source, so they see only a landing page and a claim. A public repo shows your
architecture, error handling, docs, and commit history — the actual evidence they hire on.
"Closed-source SaaS with unknown revenue" loses to "open tool with 50 stars and 10 real
users" in nearly every interview.

## Options, ranked for your situation

### 1. Free & open source, polished — best hiring-ROI, do this first
Public GitHub repo, great README, a 60-second demo GIF/video of a Notion page turning
into working code by itself, a short blog post ("I made Claude/GLM build my side projects
while I sleep"). Post it to r/ClaudeAI, the OpenCode Discord, Hacker News. Users, stars,
and issues you responded to are the credential.

### 2. Open core + paid hosted tier — best "business sense" signal
Keep this CLI free and open. Sell the thing that *can't* be copied: a hosted version.
- Cloud scheduler (no PC left running), Notion **OAuth** (no token copy-pasting),
  a web dashboard of runs/logs, email/Discord notifications, multi-queue support.
- Price it $5/mo or ~$29/yr. Even **three** paying users gives you a true story for
  interviews: "I open-sourced the engine and sold the convenience; here's what I learned
  about billing, onboarding, and churn." That story impresses more than the revenue.
- Reverse engineering stops mattering: the free tier IS the product source; people pay
  to not run infrastructure.

### 3. One-time purchase — lowest effort money
$9–19 on Gumroad/Lemon Squeezy for a "pro pack": setup video, Notion template database,
priority Discord support, pre-built config profiles for Z.AI/Kimi/MiniMax. The script
stays free; you're selling onboarding time saved. No subscription infrastructure, no
recurring support obligation.

### 4. Donations / GitHub Sponsors
Add a sponsor button day one. Won't make real money, but costs nothing and reads well.

## Recommended path

1. **Now:** polish this repo, publish it free, write the launch post. (Fix the name if
   you go public — "autobot" is a Hasbro trademark; something like `notion-forge`,
   `queuecode`, or `overnight-dev` is safer and more searchable.)
2. **If it gets traction (>100 stars or people asking for hosting):** build the hosted
   tier behind Notion OAuth + Stripe at $5/mo. Traction first, billing second — a paywall
   on day one just guarantees nobody ever sees it.
3. **On your resume/portfolio:** lead with numbers you can show — stars, downloads,
   projects built autonomously, backends supported — not with "it's a paid product."

**Bottom line:** you can't stop reverse engineering and you don't need to. Give away the
code, sell the convenience, and let the public repo do the interviewing for you.
