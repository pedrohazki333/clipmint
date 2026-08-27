"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";

import ProfileForm from "@/components/ProfileForm";
import { getProfile } from "@/lib/api";
import type { Profile } from "@/lib/types";

export default function EditarPerfilPage() {
  const { id } = useParams<{ id: string }>();
  const [profile, setProfile] = useState<Profile | null>(null);
  const [ausente, setAusente] = useState(false);

  useEffect(() => {
    getProfile(id)
      .then(setProfile)
      .catch(() => setAusente(true));
  }, [id]);

  if (ausente) {
    return <p className="py-20 text-center text-ink-dim">Perfil não encontrado.</p>;
  }
  if (!profile) {
    return <p className="py-20 text-center text-ink-dim">Carregando...</p>;
  }
  return <ProfileForm profile={profile} />;
}
