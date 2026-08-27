/**
 * Os ícones que um perfil pode usar.
 *
 * Chaves, não arquivos: o backend guarda a string e a interface desenha. Não é
 * upload de imagem — isso seria funcionalidade nova, e esta passada reorganiza
 * o que existe em vez de acrescentar.
 *
 * A lista tem que casar com `AVATARES` em `backend/app/services/profiles.py`;
 * uma chave desconhecida cai no padrão lá e desenha `person` aqui.
 */

import type { ReactNode } from "react";

export const AVATARS = [
  "mic",
  "gamepad",
  "target",
  "person",
  "video",
  "sparkles",
] as const;

export type AvatarKey = (typeof AVATARS)[number];

export const AVATAR_LABEL: Record<AvatarKey, string> = {
  mic: "Microfone",
  gamepad: "Controle",
  target: "Mira",
  person: "Pessoa",
  video: "Vídeo",
  sparkles: "Brilho",
};

const PATHS: Record<AvatarKey, ReactNode> = {
  mic: (
    <>
      <rect x="9" y="2" width="6" height="11" rx="3" />
      <path d="M5 10a7 7 0 0 0 14 0M12 17v4M8 21h8" />
    </>
  ),
  gamepad: (
    <>
      <path d="M6 11h4M8 9v4M15 12h.01M18 10h.01" />
      <rect x="2" y="6" width="20" height="12" rx="4" />
    </>
  ),
  target: (
    <>
      <circle cx="12" cy="12" r="9" />
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v3M12 19v3M2 12h3M19 12h3" />
    </>
  ),
  person: (
    <>
      <circle cx="12" cy="8" r="4" />
      <path d="M4 21a8 8 0 0 1 16 0" />
    </>
  ),
  video: (
    <>
      <rect x="2" y="6" width="14" height="12" rx="2" />
      <path d="m22 8-6 4 6 4V8z" />
    </>
  ),
  sparkles: (
    <>
      <path d="M12 3l1.8 4.2L18 9l-4.2 1.8L12 15l-1.8-4.2L6 9l4.2-1.8z" />
      <path d="M18 15l.9 2.1L21 18l-2.1.9L18 21l-.9-2.1L15 18l2.1-.9z" />
    </>
  ),
};

/** Normaliza qualquer string para uma chave que a interface sabe desenhar. */
export function avatarKey(value: string | null | undefined): AvatarKey {
  return (AVATARS as readonly string[]).includes(value ?? "")
    ? (value as AvatarKey)
    : "person";
}

export function AvatarIcon({
  name,
  className = "h-5 w-5",
}: {
  name: string | null | undefined;
  className?: string;
}) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={className}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {PATHS[avatarKey(name)]}
    </svg>
  );
}
