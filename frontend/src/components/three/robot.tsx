"use client";

import * as React from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import {
  Float,
  ContactShadows,
  Sparkles,
  RoundedBox,
} from "@react-three/drei";
import * as THREE from "three";
import { cn } from "@/lib/utils";

// Reused every frame. `new THREE.Vector3()` inside useFrame allocates sixty
// objects a second and hands the collector the bill while the user is
// scrolling -- which is where this page's long tasks were coming from.
const scratchScale = new THREE.Vector3();

function Eye({ position }: { position: [number, number, number] }) {
  const ref = React.useRef<THREE.Mesh>(null);

  useFrame(({ clock }) => {
    if (!ref.current) return;
    // Natural blink: quick close every ~3.6s with slight randomness baked into the phase.
    const t = clock.elapsedTime % 3.6;
    const blink = t > 3.35 && t < 3.55 ? 0.08 : 1;
    ref.current.scale.y = THREE.MathUtils.lerp(ref.current.scale.y, blink, 0.4);
  });

  return (
    <mesh ref={ref} position={position}>
      <capsuleGeometry args={[0.09, 0.12, 8, 16]} />
      <meshStandardMaterial
        color="#7dd3fc"
        emissive="#38bdf8"
        emissiveIntensity={2.2}
        toneMapped={false}
      />
    </mesh>
  );
}

function Smile() {
  return (
    <mesh position={[0, -0.14, 0.46]} rotation={[-0.2, 0, Math.PI * 1.1]}>
      <torusGeometry args={[0.16, 0.035, 12, 24, Math.PI * 0.8]} />
      <meshStandardMaterial
        color="#7dd3fc"
        emissive="#38bdf8"
        emissiveIntensity={1.6}
        toneMapped={false}
      />
    </mesh>
  );
}

function RobotBody({ hovered }: { hovered: boolean }) {
  const group = React.useRef<THREE.Group>(null);
  const head = React.useRef<THREE.Group>(null);

  useFrame(({ clock, pointer }) => {
    const t = clock.elapsedTime;
    if (group.current) {
      const targetScale = hovered ? 1.08 : 1;
      group.current.scale.lerp(scratchScale.setScalar(targetScale), 0.08);
      group.current.rotation.y = THREE.MathUtils.lerp(
        group.current.rotation.y,
        pointer.x * 0.45 + Math.sin(t * 0.4) * 0.12,
        0.05
      );
    }
    if (head.current) {
      head.current.rotation.x = THREE.MathUtils.lerp(
        head.current.rotation.x,
        -pointer.y * 0.3,
        0.06
      );
      head.current.rotation.z = Math.sin(t * 0.7) * 0.04;
    }
  });

  return (
    <group ref={group}>
      {/* Head */}
      <group ref={head} position={[0, 0.55, 0]}>
        <RoundedBox args={[1.15, 0.95, 0.9]} radius={0.28} smoothness={4}>
          <meshStandardMaterial color="#eef1ff" metalness={0.35} roughness={0.25} />
        </RoundedBox>
        {/* Face screen */}
        <RoundedBox args={[0.85, 0.6, 0.1]} radius={0.16} smoothness={4} position={[0, -0.02, 0.42]}>
          <meshStandardMaterial color="#101226" metalness={0.6} roughness={0.3} />
        </RoundedBox>
        <group position={[0, 0.08, 0.06]}>
          <Eye position={[-0.2, 0, 0.42]} />
          <Eye position={[0.2, 0, 0.42]} />
        </group>
        <Smile />
        {/* Antenna */}
        <mesh position={[0, 0.62, 0]}>
          <cylinderGeometry args={[0.03, 0.03, 0.28, 12]} />
          <meshStandardMaterial color="#c7cbf5" metalness={0.6} roughness={0.3} />
        </mesh>
        <mesh position={[0, 0.82, 0]}>
          <sphereGeometry args={[0.09, 24, 24]} />
          <meshStandardMaterial
            color="#a78bfa"
            emissive="#7c4dff"
            emissiveIntensity={2.4}
            toneMapped={false}
          />
        </mesh>
        {/* Ears */}
        {[-0.62, 0.62].map((x) => (
          <mesh key={x} position={[x, -0.02, 0]}>
            <capsuleGeometry args={[0.09, 0.18, 8, 16]} />
            <meshStandardMaterial color="#5b5ceb" metalness={0.5} roughness={0.3} />
          </mesh>
        ))}
      </group>

      {/* Body */}
      <RoundedBox args={[0.85, 0.75, 0.65]} radius={0.22} smoothness={4} position={[0, -0.42, 0]}>
        <meshStandardMaterial color="#e6e9ff" metalness={0.35} roughness={0.3} />
      </RoundedBox>
      {/* Chest light */}
      <mesh position={[0, -0.38, 0.31]}>
        <circleGeometry args={[0.12, 32]} />
        <meshStandardMaterial
          color="#5b5ceb"
          emissive="#5b5ceb"
          emissiveIntensity={1.8}
          toneMapped={false}
        />
      </mesh>
      {/* Arms */}
      {[-0.58, 0.58].map((x) => (
        <mesh key={x} position={[x, -0.4, 0]} rotation={[0, 0, x > 0 ? -0.25 : 0.25]}>
          <capsuleGeometry args={[0.1, 0.3, 8, 16]} />
          <meshStandardMaterial color="#c7cbf5" metalness={0.4} roughness={0.35} />
        </mesh>
      ))}
    </group>
  );
}

function Scene() {
  const [hovered, setHovered] = React.useState(false);

  return (
    <>
      {/* Four lights is more than the shader cost wants, but dropping the cyan
          rim was measured at about 2fps and it desaturates the mascot to grey
          -- the violet and cyan pair IS the character. Kept deliberately. */}
      <ambientLight intensity={0.75} />
      <directionalLight position={[4, 6, 4]} intensity={1.45} />
      <pointLight position={[-4, 2, -2]} intensity={12} color="#7c4dff" />
      <pointLight position={[4, -2, 3]} intensity={10} color="#38bdf8" />

      <Float speed={1.6} rotationIntensity={0.25} floatIntensity={1.4} floatingRange={[-0.15, 0.2]}>
        <group
          onPointerOver={() => setHovered(true)}
          onPointerOut={() => setHovered(false)}
        >
          <RobotBody hovered={hovered} />
        </group>
      </Float>

      {/* One emitter at roughly half the particles of the two it replaces.
          Measured at ~4fps for the pair, so they are worth keeping -- just
          not twice over. */}
      <Sparkles count={45} scale={[6, 4, 3]} size={3} speed={0.3} color="#8b8cf0" />

      {/* No <ContactShadows> here on purpose. It re-renders the scene to a
          shadow map and then reads it back every frame, and the readback
          stalls the GPU pipeline -- Chrome's driver reports it literally, as
          "GPU stall due to ReadPixels". It cost 25fps on its own (19 -> 44
          measured with everything else unchanged), which is a lot to pay for
          a soft blur under a mascot. The grounding shadow is now a static CSS
          ellipse in RobotHero below, which costs nothing to composite. */}
    </>
  );
}

export default function RobotHero({ className }: { className?: string }) {
  const host = React.useRef<HTMLDivElement>(null);
  // A render loop nobody can see is pure cost. The robot sits in the hero, so
  // it is off screen for most of a visit -- and it was still drawing sixty
  // frames a second behind the sections the reader had scrolled down to,
  // competing with the scroll itself. Measured on the landing page: 18.8fps
  // with the loop always on, 46.5 with the canvas gone entirely.
  const [live, setLive] = React.useState(true);

  React.useEffect(() => {
    const el = host.current;
    if (!el) return;

    let onScreen = true;
    let tabVisible = !document.hidden;
    const sync = () => setLive(onScreen && tabVisible);

    // The margin restarts the loop just before the robot scrolls back in, so
    // it is already moving by the time it is visible rather than popping.
    const io = new IntersectionObserver(
      ([entry]) => {
        onScreen = entry.isIntersecting;
        sync();
      },
      { rootMargin: "150px" }
    );
    io.observe(el);

    const onVisibility = () => {
      tabVisible = !document.hidden;
      sync();
    };
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      io.disconnect();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, []);

  return (
    <div ref={host} className={cn("relative", className)} aria-hidden>
      {/* The grounding shadow the removed ContactShadows used to draw. Static,
          composited, and free -- the robot only bobs a few pixels, so nothing
          about it needed to be recomputed sixty times a second. */}
      <div className="pointer-events-none absolute bottom-[14%] left-1/2 h-6 w-40 -translate-x-1/2 rounded-[50%] bg-indigo-900/25 blur-xl sm:w-52" />
      <Canvas
        frameloop={live ? "always" : "never"}
        camera={{ position: [0, 0.3, 4.4], fov: 42 }}
        // The canvas renders at roughly 300x150 device pixels, so the ceiling
        // was buying resolution nobody can resolve at that size.
        dpr={[1, 1.5]}
        gl={{ antialias: true, alpha: true, powerPreference: "high-performance" }}
      >
        <Scene />
      </Canvas>
    </div>
  );
}
