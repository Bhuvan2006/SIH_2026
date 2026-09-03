import { Link, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useScrolled } from "../hooks/useScrolled";
import { Button } from "../components/ui";

interface Feature {
  icon: string;
  title: string;
  body: string;
}

const FEATURES: Feature[] = [
  {
    icon: "⏰",
    title: "Reminders that reach you",
    body: "A nudge at every dose time — on your phone, or by SMS when the app isn't open. Mark each dose taken, skipped, or snoozed in one tap.",
  },
  {
    icon: "📄",
    title: "Prescriptions, understood",
    body: "Photograph a prescription and Arogya reads the medicines, strengths, and schedule. You review and confirm every field before anything is saved.",
  },
  {
    icon: "🗂️",
    title: "One lifelong health record",
    body: "Every prescription, condition, and dose you've logged, in one timeline you can scroll back through — or export as a PDF to hand your doctor.",
  },
  {
    icon: "💬",
    title: "Answers you can check",
    body: "Ask about storage, interactions, or what's unsafe in pregnancy. Every medical claim cites the source it came from, and emergencies are sent straight to real help.",
  },
  {
    icon: "💰",
    title: "The same medicine, for less",
    body: "See generic equivalents with the same composition and strength, including Jan Aushadhi options — so you can ask your pharmacist an informed question.",
  },
  {
    icon: "🗣️",
    title: "In your own language",
    body: "The whole app works in English, Hindi, and Tamil, with more on the way. Explanations get translated; medicine names deliberately don't.",
  },
];

const STEPS = [
  {
    title: "Snap your prescription",
    body: "Photograph it in any language. Arogya extracts each medicine and dosage automatically.",
  },
  {
    title: "Check and confirm",
    body: "You review every extracted field and correct anything wrong. Nothing is saved until you say so.",
  },
  {
    title: "Get reminded, stay on track",
    body: "Reminders fire at each dose time, adherence is logged, and your history builds itself.",
  },
];

export default function Landing() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const scrolled = useScrolled();

  return (
    <div className="landing">
      {/* ---------- Top bar ---------- */}
      <header className={`topbar ${scrolled ? "is-scrolled" : ""}`}>
        <Link to="/welcome" className="brand">
          🩺 {t("appName")}
        </Link>
        <div style={{ flex: 1 }} />
        <div className="topbar-right">
          <Button variant="ghost" onClick={() => navigate("/login")}>
            {t("login")}
          </Button>
          <Button onClick={() => navigate("/login")}>Get started</Button>
        </div>
      </header>

      {/* ---------- Hero ---------- */}
      <section className="hero">
        <div className="hero__blob hero__blob--a" aria-hidden="true" />
        <div className="hero__blob hero__blob--b" aria-hidden="true" />

        <div className="hero__inner">
          <div>
            <p className="hero__eyebrow animate-in">
              <span aria-hidden="true">✨</span> Your health, organised
            </p>

            <h1 className="hero__title animate-in animate-in-1">
              Life gets busy.
              <br />
              <span className="hero__title-accent">Your medicines shouldn't slip.</span>
            </h1>

            <p className="hero__subtitle animate-in animate-in-2">
              Arogya keeps every prescription, dose, and appointment in one place — and reminds you
              at the right moment, in your own language. Built for people juggling work, family, and
              a health condition that doesn't wait for a free afternoon.
            </p>

            <div className="hero__actions animate-in animate-in-3">
              <Button size="lg" onClick={() => navigate("/login")}>
                Start free with your phone number
              </Button>
              <Button size="lg" variant="ghost" onClick={() => navigate("/login")}>
                See how it works
              </Button>
            </div>

            <div className="hero__trust animate-in animate-in-4">
              <span className="hero__trust-item">
                <span aria-hidden="true">🔒</span> Your data stays yours
              </span>
              <span className="hero__trust-item">
                <span aria-hidden="true">🩺</span> Every answer cites its source
              </span>
              <span className="hero__trust-item">
                <span aria-hidden="true">📵</span> No app install needed
              </span>
            </div>
          </div>

          {/* Product preview: the reminder list, which is the daily heart of the app. */}
          <div className="hero__card animate-in animate-in-2">
            <div className="hero__card-head">
              <span className="hero__card-title">Today&rsquo;s doses</span>
              <span className="hero__pill">2 of 3 done</span>
            </div>

            <div className="hero__dose">
              <span className="hero__dose-time">08:00</span>
              <span>
                <span className="hero__dose-name">Metformin 500mg</span>
                <br />
                <span className="hero__dose-sub">After breakfast</span>
              </span>
              <span className="hero__dose-check" aria-hidden="true">
                ✓
              </span>
            </div>

            <div className="hero__dose">
              <span className="hero__dose-time">14:00</span>
              <span>
                <span className="hero__dose-name">Amlodipine 5mg</span>
                <br />
                <span className="hero__dose-sub">With water</span>
              </span>
              <span className="hero__dose-check" aria-hidden="true">
                ✓
              </span>
            </div>

            <div className="hero__dose">
              <span className="hero__dose-time">21:00</span>
              <span>
                <span className="hero__dose-name">Insulin Glargine</span>
                <br />
                <span className="hero__dose-sub">❄️ Keep refrigerated 2–8°C</span>
              </span>
              <span className="hero__dose-check hero__dose-check--pending" aria-hidden="true">
                ○
              </span>
            </div>
          </div>
        </div>
      </section>

      {/* ---------- Features ---------- */}
      <section className="section">
        <div className="section__head">
          <h2 className="section__title">Everything about your health, in one place</h2>
          <p className="section__lead">
            Prescriptions, reminders, medical history, and honest answers — so nothing depends on
            remembering it yourself.
          </p>
        </div>

        <div className="feature-grid">
          {FEATURES.map((f) => (
            <article className="feature" key={f.title}>
              <div className="feature__icon" aria-hidden="true">
                {f.icon}
              </div>
              <h3 className="feature__title">{f.title}</h3>
              <p className="feature__body">{f.body}</p>
            </article>
          ))}
        </div>
      </section>

      {/* ---------- How it works ---------- */}
      <section className="section" style={{ paddingTop: 0 }}>
        <div className="section__head">
          <h2 className="section__title">Three steps, about a minute</h2>
          <p className="section__lead">
            No forms to fill in, no records to type up. Start from the prescription you already have
            in your hand.
          </p>
        </div>

        <div className="steps">
          {STEPS.map((s, i) => (
            <div className="step" key={s.title}>
              <div className="step__num" aria-hidden="true">
                {i + 1}
              </div>
              <h3 className="step__title">{s.title}</h3>
              <p className="step__body">{s.body}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ---------- Closing CTA ---------- */}
      <section className="landing-cta">
        <h2>Start with your next dose</h2>
        <p>
          Sign in with your phone number — no password to remember, no card required. Your first
          prescription takes under a minute to add.
        </p>
        <Button size="lg" variant="secondary" onClick={() => navigate("/login")}>
          Get started free
        </Button>
      </section>

      <footer className="landing-footer">
        <p style={{ margin: 0 }}>
          Arogya provides general health information and medication reminders. It does not diagnose,
          prescribe, or replace your doctor or pharmacist — always confirm medical decisions with
          them.
        </p>
      </footer>
    </div>
  );
}
