# Laravel

## Detect

`artisan` and a `composer.json` that requires `laravel/framework`. The `package.json` next to it is
the Laravel frontend, not a separate Node stack.

## Layout

Laravel's structure is the target. `app/`, `bootstrap/`, `config/`, `database/`, `lang/`, `public/`,
`resources/`, `routes/`, `storage/`, `tests/` stay where they are.

- Inside `app/`, follow patterns the project already uses (Actions, Services, Livewire, Filament,
  Enums, DTOs). Never introduce a new one.
- PSR-4: class name = file name, namespace = folder. Moving a class means updating its namespace,
  every `use` statement, and string references (config arrays, route definitions, service provider
  bindings, policies, `morphMap`).
- Module blocks for large projects: a domain = its routes plus the controllers, requests, models,
  policies, views, and tests they use. Discover domains from `routes/*.php`.

## Contracts (in addition to rules.md)

Route names and URIs, config keys, `.env` keys, database tables and columns, existing migrations,
Blade view names used as strings, translation keys, artisan command signatures, API resource
fields, Livewire component names, Filament resource slugs, and every class name that can be stored
in the database: models in polymorphic relations, queued jobs, notifications, events, casts.
Renaming or moving such a class falls under the doubt policy.

## Tests

- Command: `php artisan test` (or `vendor/bin/pest` / `vendor/bin/phpunit` when that is what the
  project uses).
- Tests must use the testing database from `phpunit.xml` (usually SQLite in memory). If
  `phpunit.xml` does not set `DB_CONNECTION` for testing, skip database-backed tests and report it.
- Use factories and fakes: `Http::fake()`, `Mail::fake()`, `Queue::fake()`, `Notification::fake()`,
  `Storage::fake()`, `Event::fake()` where events trigger external work.
- `vendor/` missing → `composer install --no-interaction`. Never `composer update` or
  `composer require` for runtime packages.

## Formatter

`php vendor/bin/pint` when `vendor/bin/pint` exists; respects `pint.json`. Commit
`style: format with pint`. Frontend formatting only through an existing `package.json` script.

## Smoke checks

- `php artisan route:list > /dev/null`
- `php -l <file>` for every changed PHP file
- After moving classes: `composer dump-autoload`
- Frontend paths changed and `node_modules/` exists: `npm run build`

## Pitfalls

- Blade component classes (`app/View/Components/Foo.php`) and views
  (`resources/views/components/foo.blade.php`) are coupled by name.
- Production runs on case-sensitive Linux: file names and references must match in case exactly.
- `vite.config.js` inputs and `@vite([...])` directives both list asset paths.
- `.env.example` keys are contracts; don't rename or remove them.
