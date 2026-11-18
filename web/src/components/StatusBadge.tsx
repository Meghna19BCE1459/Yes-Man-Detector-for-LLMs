export default function StatusBadge({ status }: { status: string }) {
  const label: Record<string, string> = {
    running: "Running",
    finished: "Finished",
    error: "Error",
    interrupted: "Interrupted",
  };
  return (
    <span className={`badge ${status}`}>
      <span className="dot" />
      {label[status] ?? status}
    </span>
  );
}
