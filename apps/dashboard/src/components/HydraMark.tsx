const HEAD =
  'M-2.4 -1.2 C-0.4 -1.5 1 -2.3 3 -2.1 C4.8 -1.9 6.2 -1.1 6.8 -0.3 C7 0 6.9 0.4 6.6 0.6 ' +
  'C5.4 1.5 3.6 2.1 2 2.1 C0.4 2.1 -0.6 1.4 -2.4 1.2 Z ' +
  'M3.95 -0.65 A0.6 0.6 0 1 0 2.75 -0.65 A0.6 0.6 0 1 0 3.95 -0.65 Z'

/**
 * Three serpent necks from one body: the hydra, and one root manifest
 * branching into its dependencies. Each head sits on its neck's final
 * tangent; the left one is mirrored so its eye stays on top.
 */
const HEADS = [
  'translate(18.3 6.4) rotate(-45)',
  'translate(7.2 8.3) rotate(150.3) scale(1 -1)',
  'translate(24.8 8.3) rotate(29.7)',
]

export function HydraMark({ size = 24, className = '' }: { size?: number; className?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      stroke="currentColor"
      strokeWidth={2.4}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden
    >
      <path d="M8.5 30.4 C12.5 30.4 16 29 16 25.5" />
      <path d="M16 25.5 C16 21.5 13.4 19.5 14.1 15.2 C14.5 12.6 15.2 10.4 16.3 8.8 C16.9 7.9 17.5 7.2 18.3 6.4" />
      <path d="M16 25.5 C11.5 25.5 8.5 22.5 9 17.5 C9.4 13.6 10.6 10.4 9.4 8.8 C8.8 8 7.9 7.9 7.2 8.3" />
      <path d="M16 25.5 C20.5 25.5 23.5 22.5 23 17.5 C22.6 13.6 21.4 10.4 22.6 8.8 C23.2 8 24.1 7.9 24.8 8.3" />
      <g fill="currentColor" fillRule="evenodd" stroke="none">
        {HEADS.map((transform) => (
          <path key={transform} d={HEAD} transform={transform} />
        ))}
      </g>
    </svg>
  )
}
