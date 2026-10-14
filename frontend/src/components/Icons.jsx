function Icon({ size = 18, children, ...rest }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...rest}
    >
      {children}
    </svg>
  )
}

export const ScaleIcon = (p) => (
  <Icon {...p}>
    <path d="M12 3v18M7 21h10M5 7h14" />
    <path d="M5 7l-3 7a3 3 0 0 0 6 0L5 7zM19 7l-3 7a3 3 0 0 0 6 0l-3-7z" />
  </Icon>
)

export const ArrowRightIcon = (p) => (
  <Icon strokeWidth="2" {...p}>
    <path d="M5 12h14M13 6l6 6-6 6" />
  </Icon>
)

export const ExternalIcon = (p) => (
  <Icon strokeWidth="1.8" {...p}>
    <path d="M7 17L17 7M9 7h8v8" />
  </Icon>
)

export const CopyIcon = (p) => (
  <Icon {...p}>
    <rect x="9" y="9" width="11" height="11" rx="2" />
    <path d="M5 15V6a2 2 0 0 1 2-2h8" />
  </Icon>
)

export const CheckIcon = (p) => (
  <Icon strokeWidth="2" {...p}>
    <path d="M5 12.5l4.5 4.5L19 7" />
  </Icon>
)

export const ThumbUpIcon = (p) => (
  <Icon {...p}>
    <path d="M7 11v9H4v-9h3zM7 11l4-8c1.5 0 2.5 1 2.2 2.6L12.7 9H19a2 2 0 0 1 2 2.4l-1.2 6A2 2 0 0 1 17.9 19H7" />
  </Icon>
)

export const ThumbDownIcon = (p) => (
  <Icon style={{ transform: 'scaleY(-1)' }} {...p}>
    <path d="M7 11v9H4v-9h3zM7 11l4-8c1.5 0 2.5 1 2.2 2.6L12.7 9H19a2 2 0 0 1 2 2.4l-1.2 6A2 2 0 0 1 17.9 19H7" />
  </Icon>
)

export const RedoIcon = (p) => (
  <Icon {...p}>
    <path d="M20 5v5h-5M20 10a8 8 0 1 0 1.5 5" />
  </Icon>
)

export const PlusIcon = (p) => (
  <Icon strokeWidth="2" {...p}>
    <path d="M12 5v14M5 12h14" />
  </Icon>
)

export const CloseIcon = (p) => (
  <Icon strokeWidth="2" {...p}>
    <path d="M6 6l12 12M18 6L6 18" />
  </Icon>
)

export const MenuIcon = (p) => (
  <Icon {...p}>
    <path d="M4 7h16M4 12h16M4 17h16" />
  </Icon>
)

export const SidebarIcon = (p) => (
  <Icon {...p}>
    <rect x="3" y="4" width="18" height="16" rx="2" />
    <path d="M9 4v16" />
  </Icon>
)

export const PencilIcon = (p) => (
  <Icon {...p}>
    <path d="M4 20l1-4L16.5 4.5a2 2 0 0 1 3 3L8 19l-4 1z" />
  </Icon>
)

export const TrashIcon = (p) => (
  <Icon {...p}>
    <path d="M4 7h16M10 7V4h4v3M6 7l1 13h10l1-13M10 11v6M14 11v6" />
  </Icon>
)

export const LockIcon = (p) => (
  <Icon {...p}>
    <rect x="5" y="11" width="14" height="9" rx="2" />
    <path d="M8 11V8a4 4 0 0 1 8 0v3" />
  </Icon>
)

export const SunIcon = (p) => (
  <Icon {...p}>
    <circle cx="12" cy="12" r="4" />
    <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
  </Icon>
)

export const MoonIcon = (p) => (
  <Icon {...p}>
    <path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z" />
  </Icon>
)

export const AlertIcon = (p) => (
  <Icon {...p}>
    <path d="M12 4l9 16H3L12 4zM12 10v4M12 17v.5" />
  </Icon>
)
