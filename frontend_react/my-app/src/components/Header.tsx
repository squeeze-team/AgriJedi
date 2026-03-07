export function Header() {
  return (
    <header className="cyber-header flex flex-wrap items-center justify-between gap-4 px-5 py-4 md:px-7">
      <div className="flex items-center gap-3">
        <h1 className="text-xl font-bold tracking-tight">
          <span style={{ color: '#2e9e6e' }}>Agro</span>
          <span style={{ color: '#1b3a5c' }}>Mind</span>
        </h1>
        <span className="cyber-badge">FRANCE NODE</span>
      </div>

      <div className="flex items-center gap-2 text-sm">
        <span className="cyber-pill">LIVE</span>
        <span className="cyber-pill">Country: France</span>
      </div>
    </header>
  );
}
