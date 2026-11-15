import { ButtonLink } from "@/components/ui";

export default function NotFound() {
  return (
    <div className="space-y-4 py-10 text-center">
      <h1 className="text-3xl font-bold">Page not found</h1>
      <p className="text-muted">
        We could not find what you were looking for.
      </p>
      <ButtonLink href="/doctors">Find a doctor</ButtonLink>
    </div>
  );
}
