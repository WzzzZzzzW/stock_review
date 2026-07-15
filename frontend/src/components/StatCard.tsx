interface Props {
  label: string
  value: string | number
  positive?: boolean | null
}

export default function StatCard({ label, value, positive }: Props) {
  const color =
    positive === true
      ? 'text-rise'
      : positive === false
        ? 'text-fall'
        : 'text-white'

  return (
    <div className="bg-gray-800 rounded-lg px-4 py-3">
      <div className="text-xs text-gray-400 mb-1">{label}</div>
      <div className={`text-base font-semibold ${color}`}>{value}</div>
    </div>
  )
}
