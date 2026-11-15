import Image from "next/image";

/** Hero photo: Vitaly Gariev on Unsplash (Unsplash License, free for commercial use). */
export function DoctorHero() {
  return (
    <figure className="overflow-hidden rounded-2xl border border-border bg-primary-soft shadow-sm">
      <Image
        src="/images/clinic-doctor.jpg"
        alt="A doctor in a white coat with a stethoscope talking with a patient in a bright clinic office"
        width={1400}
        height={788}
        priority
        sizes="(min-width: 768px) 50vw, 100vw"
        className="h-72 w-full object-cover object-[60%_30%] sm:h-96"
      />
    </figure>
  );
}
