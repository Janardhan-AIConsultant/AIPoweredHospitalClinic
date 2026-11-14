import { ButtonLink, Card } from "@/components/ui";

const STEPS = [
  {
    title: "Find a doctor",
    body: "Browse our doctors by specialty and see their working days and consultation fee.",
  },
  {
    title: "Pick a time",
    body: "Choose an open slot that suits you. Only times that are really free are shown.",
  },
  {
    title: "Confirm",
    body: "Enter your name and mobile number. No account or password needed.",
  },
];

export default function HomePage() {
  return (
    <div className="space-y-12">
      <section className="space-y-5 py-6">
        <h1 className="max-w-2xl text-4xl font-bold tracking-tight sm:text-5xl">
          Book your doctor appointment in under a minute
        </h1>
        <p className="max-w-xl text-lg text-muted">
          Bindu AI Clinic makes it simple to see the right doctor. Choose a
          specialist, pick a time and you are done.
        </p>
        <div className="flex flex-wrap gap-3">
          <ButtonLink href="/doctors">Find a doctor</ButtonLink>
        </div>
      </section>

      <section aria-labelledby="how">
        <h2 id="how" className="text-2xl font-semibold">
          How it works
        </h2>
        <ol className="mt-4 grid gap-4 sm:grid-cols-3">
          {STEPS.map((s, i) => (
            <li key={s.title}>
              <Card className="h-full">
                <span className="text-sm font-bold text-primary">
                  Step {i + 1}
                </span>
                <h3 className="mt-1 font-semibold">{s.title}</h3>
                <p className="mt-1 text-sm text-muted">{s.body}</p>
              </Card>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
