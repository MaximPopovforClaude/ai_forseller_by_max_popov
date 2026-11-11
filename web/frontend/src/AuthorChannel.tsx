export const AUTHOR_CHANNEL = "https://t.me/maxim_popov_wb";

/** Public author attribution, independent of the installation's support contacts. */
export function AuthorChannel() {
  return <p><a className="about-btn" href={AUTHOR_CHANNEL} target="_blank" rel="noopener noreferrer">
    Канал автора платформы: @maxim_popov_wb →
  </a></p>;
}
