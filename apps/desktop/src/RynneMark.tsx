type RynneMarkProps = {
  size?: number;
  className?: string;
};

export function RynneMark({ size = 24, className }: RynneMarkProps) {
  const classes = ["rynne-mark", className].filter(Boolean).join(" ");
  return (
    <img
      className={classes}
      src="/rynne-icon-green.png"
      width={size}
      alt=""
      aria-hidden="true"
      draggable={false}
    />
  );
}
