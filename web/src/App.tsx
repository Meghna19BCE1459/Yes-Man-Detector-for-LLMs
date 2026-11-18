import { useEffect, useState } from "react";
import HomePage from "./pages/HomePage";
import RunPage from "./pages/RunPage";
import NewRunPage from "./pages/NewRunPage";
import DebatePage from "./pages/DebatePage";

function useHashRoute(): string[] {
  const read = () => window.location.hash.replace(/^#\/?/, "").split("/").filter(Boolean).map(decodeURIComponent);
  const [parts, setParts] = useState(read);
  useEffect(() => {
    const on = () => {
      setParts(read());
      window.scrollTo(0, 0);
    };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return parts;
}

export const go = (path: string) => {
  window.location.hash = path;
};

function ThemeToggle() {
  const [theme, setTheme] = useState<string | null>(() => {
    try {
      return localStorage.getItem("theme");
    } catch {
      return null;
    }
  });
  useEffect(() => {
    if (theme) document.documentElement.setAttribute("data-theme", theme);
    else document.documentElement.removeAttribute("data-theme");
  }, [theme]);
  const isDark = theme ? theme === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches;
  const flip = () => {
    const next = isDark ? "light" : "dark";
    setTheme(next);
    try {
      localStorage.setItem("theme", next);
    } catch {
      /* private mode */
    }
  };
  return (
    <button className="theme-btn" onClick={flip} aria-label={`Switch to ${isDark ? "light" : "dark"} theme`} title="Toggle theme">
      {isDark ? "☀" : "☾"}
    </button>
  );
}

function Logo() {
  return (
    <svg width="26" height="26" viewBox="0 0 32 32" aria-hidden="true">
      <line x1="9" y1="16" x2="23" y2="9" stroke="var(--axis)" strokeWidth="2" />
      <line x1="9" y1="16" x2="23" y2="23" stroke="var(--axis)" strokeWidth="2" />
      <line x1="23" y1="9" x2="23" y2="23" stroke="var(--axis)" strokeWidth="2" />
      <circle cx="9" cy="16" r="5" fill="var(--series-1)" />
      <circle cx="23" cy="9" r="5" fill="var(--muted)" />
      <circle cx="23" cy="23" r="5" fill="var(--muted)" />
    </svg>
  );
}

export default function App() {
  const route = useHashRoute();
  const [head, id] = route;
  let page;
  if (head === "runs" && id) page = <RunPage key={id} runId={id} />;
  else if (head === "new") page = <NewRunPage />;
  else if (head === "debate") page = <DebatePage key={id ?? "new"} runId={id} />;
  else page = <HomePage />;

  const link = (href: string, label: string, active: boolean) => (
    <a href={href} className={active ? "active" : ""}>
      {label}
    </a>
  );

  return (
    <>
      <header className="topbar">
        <div className="topbar-inner">
          <a href="#/" className="brand">
            <Logo />
            <span className="brand-text">
              <span className="brand-name">Yes-Man Detector</span>
              <span className="brand-sub">for LLMs</span>
            </span>
          </a>
          <nav className="nav">
            {link("#/", "Results", !head || head === "runs")}
            {link("#/debate", "Live debate", head === "debate")}
            {link("#/new", "New experiment", head === "new")}
          </nav>
          <ThemeToggle />
        </div>
      </header>
      <main>{page}</main>
      <footer>Do language models abandon the truth under peer pressure? An open experiment.</footer>
    </>
  );
}
