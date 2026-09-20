# Android and Gradle projects

## Detect

`settings.gradle`, `settings.gradle.kts`, `build.gradle` or `build.gradle.kts` plus a `gradlew`
wrapper. Android when a module applies `com.android.application` or `com.android.library`, or has
`src/main/AndroidManifest.xml`. A Gradle module inside a larger repository (for example
`apps/<name>/`) is a secondary stack: the repository root keeps its own stack's layout, and the
Gradle module is tidied under the rules here.

## Contracts (in addition to rules.md)

Anything below is part of how devices, stores and management systems find this app. None of it
changes:

- `applicationId` and the package name, including every `android:name` in the manifest
  (activities, services, receivers, providers) and the `<application android:name>` class. Device
  owner, kiosk allowlists, MDM policies and launcher intents refer to these strings.
- `versionCode` and `versionName`.
- Permissions, `<intent-filter>` actions and categories, exported flags, `android:authorities`,
  deep links, `queries` entries.
- Resource names used from outside the module: string, drawable, layout, style, XML config files
  in `res/xml` (device admin, accessibility, backup rules, network security config).
- `SharedPreferences` file names and keys, database names, file paths on device, broadcast action
  strings, intent extras, and any class name a `ComponentName` is built from.
- The Gradle wrapper (`gradlew`, `gradlew.bat`, `gradle/wrapper/*`), module names in
  `settings.gradle`, build type and product flavour names, signing configs, `proguard-rules.pro`
  (and any `-keep` rule's class names).
- Property files the build or app reads at runtime (`local.properties`, `fleet.properties`,
  `gradle.properties`, `*.properties.example`), and assets folders referenced by path.

Class and package renames are contract changes here more often than in other stacks: apply the
doubt policy and report instead of renaming, unless every reference in manifest, XML, ProGuard
rules, reflection and test code is inside the repository and updated in the same commit.

## Target layout

Gradle and Android conventions are the layout. Do not invent a new one.

```
settings.gradle                 module list
build.gradle                    root build file
gradle.properties
gradle/wrapper/                 wrapper, untouched
gradlew, gradlew.bat            untouched
app/                            (or another module name from settings.gradle)
  build.gradle
  proguard-rules.pro
  src/main/AndroidManifest.xml
  src/main/java/<package>/…     production code, packages by feature
  src/main/res/…                resources
  src/main/assets/…
  src/test/java/<package>/…     JVM unit tests
  src/androidTest/java/…        instrumentation tests (device needed)
docs/
```

Within that structure the work is: group classes into feature packages that match what they do,
split oversized classes and functions, remove provably unused code and resources, and rename
internal identifiers to clear English. Moving a class between packages changes its fully qualified
name — treat it as a contract change (see above) and check manifest, XML, ProGuard and reflection
first.

Never move or rewrite: `build/` output, `.gradle/`, `local.properties`, keystores (`*.jks`,
`*.keystore`), `google-services.json`, generated sources.

## Tests

- Command: `./gradlew :<module>:testDebugUnitTest --console=plain` (Git Bash) or
  `cmd //c "gradlew.bat :<module>:testDebugUnitTest --console=plain"`. For a single-module project
  `./gradlew test --console=plain` is fine.
- Never run `connectedAndroidTest` or anything under `src/androidTest` — it needs a device or
  emulator. Existing instrumentation tests stay untouched; say so in the report.
- Requirements: a JDK matching the project's `jvmTarget`/`sourceCompatibility` (`java -version`,
  `JAVA_HOME`) and an Android SDK path in `local.properties` or `ANDROID_HOME`. Missing → skip the
  test and smoke blocks and report it; never write or edit `local.properties`.
- The first Gradle run downloads the distribution and dependencies and can take longer than the
  10-minute command limit. Run it once at baseline; if it does not finish in time, report that the
  build is too slow for this skill and skip the gated blocks rather than running without a gate.
- Add JVM unit tests under `src/test/java` for the logic the testing policy names (calculations,
  parsing, data transformation, auth). Use plain JUnit with the libraries the project already has
  (JUnit, Truth/AssertJ, Mockito, Robolectric) — never add a new test library.
- Android framework classes are unavailable in JVM tests: extract the logic under test into plain
  classes first (a `code` block), then test those. Do not add Robolectric to reach into the
  framework if the project does not already use it.
- Tests must not touch a real device, adb, the network, or the file system outside a temporary
  folder.

## Formatter

Only when already configured: ktlint or Spotless (`spotless`/`ktlint` plugin in a build file) →
`./gradlew spotlessApply` or `./gradlew ktlintFormat`, one commit `style: format with <tool>`.
Never add a formatter plugin, and never run `--write` style tools that are not in the build.
`.editorconfig` alone is not a formatter.

## Smoke checks

- `./gradlew :<module>:assembleDebug --console=plain` when it fits the time limit; otherwise
  `:<module>:compileDebugJavaWithJavac` (or `compileDebugKotlin`).
- `./gradlew :<module>:lintDebug` only if lint already passed at baseline; treat new lint errors as
  a failure, existing ones as baseline noise.
- After touching resources or the manifest: the assemble or compile task must still succeed —
  missing resources fail there, not in unit tests.

## Pitfalls

- `local.properties` and config property files are untracked and local: they are exactly the files
  the guard protects. Never move, rewrite or "tidy" them, and never commit an example copy with
  real values in it.
- `build/` and `.gradle/` directories appear during the baseline run; make sure they are ignored
  before the run continues, and never delete them by hand.
- Resource shrinking and ProGuard/R8 keep rules reference class and method names as strings, so
  "unused" code may be used in a release build only.
- String resources in `res/values*/strings.xml` are user-facing text: never translate, reword or
  reorder them, and never remove a translation folder.
- Layout XML references classes by name (`<com.example.MyView>`, `tools:context`) and fragments by
  `android:name`; a rename must update them in the same commit.
- Kotlin and Java can live in the same module; keep a file's language as it is (never convert).
- Gradle build scripts are code too: duplicated dependency blocks may be tidied, but version
  numbers, repositories and plugin versions stay exactly as they are.
