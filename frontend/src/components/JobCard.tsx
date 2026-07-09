import Link from "next/link";
import type { Job } from "@/lib/types";

const STATUS_LABELS: Record<string, string> = {
  queued: "Na fila",
  downloading: "Baixando",
  transcribing: "Transcrevendo",
  analyzing: "Analisando",
  clipping: "Gerando clips",
  done: "Concluído",
  error: "Erro",
};

const STATUS_COLORS: Record<string, string> = {
  queued: "text-gray-400",
  downloading: "text-blue-400",
  transcribing: "text-yellow-400",
  analyzing: "text-purple-400",
  clipping: "text-orange-400",
  done: "text-emerald-400",
  error: "text-red-400",
};

interface Props {
  job: Job;
}

export default function JobCard({ job }: Props) {
  const label = STATUS_LABELS[job.status] ?? job.status;
  const color = STATUS_COLORS[job.status] ?? "text-gray-400";

  return (
    <Link href={`/jobs/${job.id}`}>
      <div className="rounded-xl bg-gray-900 border border-gray-800 hover:border-gray-600 p-4 transition-colors cursor-pointer">
        <div className="flex items-start gap-4">
          {job.thumbnail_url && (
            <img
              src={job.thumbnail_url}
              alt={job.video_title ?? "thumbnail"}
              className="w-24 h-14 object-cover rounded-lg flex-shrink-0"
            />
          )}
          <div className="flex-1 min-w-0">
            <p className="font-medium text-gray-100 truncate">
              {job.video_title ?? job.youtube_url}
            </p>
            {job.channel_name && (
              <p className="text-sm text-gray-500 mt-0.5">{job.channel_name}</p>
            )}
            <div className="flex items-center gap-3 mt-2">
              <span className={`text-xs font-semibold ${color}`}>{label}</span>
              <span className="text-xs text-gray-600">
                {new Date(job.created_at).toLocaleString("pt-BR")}
              </span>
            </div>
          </div>
        </div>
        {job.status === "error" && job.error_message && (
          <p className="mt-2 text-xs text-red-400 bg-red-900/20 rounded px-2 py-1 truncate">
            {job.error_message}
          </p>
        )}
      </div>
    </Link>
  );
}
