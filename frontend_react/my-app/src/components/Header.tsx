export function Header() {
  return (
    <header className="cyber-header flex flex-wrap items-center justify-between gap-4 px-5 py-4 md:px-7">
      <div className="flex items-center gap-3">
        <span className="cyber-badge">FRANCE NODE</span>
        <h1 className="cyber-title text-xl font-bold">AgroMind</h1>
      </div>

      <div className="flex items-center gap-2 text-sm">
        <span className="cyber-pill">LIVE</span>
        <span className="cyber-pill">Country: France</span>
      </div>
    </header>
  );
}
