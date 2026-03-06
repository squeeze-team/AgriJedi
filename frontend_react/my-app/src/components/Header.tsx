export function Header() {
  return (
    <header className="flex flex-wrap items-center gap-4 bg-blue-600 px-5 py-4 text-white shadow-sm md:px-7">
      <h1 className="text-xl font-bold">AgriIntel</h1>

      <span className="text-sm">
        Country: <strong>France</strong>
      </span>
    </header>
  );
}
