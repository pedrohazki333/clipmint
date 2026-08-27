import { NextResponse } from "next/server";

import { AUTH_COOKIE } from "@/lib/auth";

export async function POST(req: Request) {
  const res = NextResponse.redirect(new URL("/login", req.url), { status: 303 });
  res.cookies.delete(AUTH_COOKIE);
  return res;
}
