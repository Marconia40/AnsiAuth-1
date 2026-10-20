-- Activa RLS de verdad: la aplicacion pasa a conectarse con un rol propio
-- sin SUPERUSER ni BYPASSRLS, que queda como dueno de la base y sus objetos.
--
-- Por que no se degrada ``ansiauth``: es el usuario bootstrap del cluster
-- (POSTGRES_USER de la imagen) y Postgres no permite quitarle SUPERUSER.
-- Queda como superusuario de mantenimiento (backups, restores, psql).
--
-- Uso (como ``ansiauth``, conectado a la base de la aplicacion):
--   docker exec -i ansiauth-postgres psql -U ansiauth -d ansiauth \
--       -v ON_ERROR_STOP=1 -v app_password='<clave>' < rls-rol-app.sql
--
-- Idempotente: se puede correr de nuevo sin efectos.

\set ON_ERROR_STOP 1

-- 1. Rol de la aplicacion.
SELECT format(
    'CREATE ROLE ansiauth_app LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE PASSWORD %L',
    :'app_password')
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ansiauth_app')
\gexec
ALTER ROLE ansiauth_app NOSUPERUSER NOBYPASSRLS;

-- 2. Propiedad de la base y del esquema (las migraciones crean objetos ahi).
SELECT format('ALTER DATABASE %I OWNER TO ansiauth_app', current_database())
\gexec
ALTER SCHEMA public OWNER TO ansiauth_app;

-- 3. Propiedad de tablas, vistas, secuencias sueltas, funciones y tipos.
--    Las secuencias de columnas serial/identity cambian solas con su tabla.
DO $$
DECLARE
    r record;
BEGIN
    FOR r IN
        SELECT c.relname, c.relkind
          FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
    LOOP
        EXECUTE format(
            CASE r.relkind
                WHEN 'v' THEN 'ALTER VIEW public.%I OWNER TO ansiauth_app'
                WHEN 'm' THEN 'ALTER MATERIALIZED VIEW public.%I OWNER TO ansiauth_app'
                WHEN 'f' THEN 'ALTER FOREIGN TABLE public.%I OWNER TO ansiauth_app'
                ELSE 'ALTER TABLE public.%I OWNER TO ansiauth_app'
            END, r.relname);
    END LOOP;

    FOR r IN
        SELECT c.relname
          FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = 'public' AND c.relkind = 'S'
           AND NOT EXISTS (
               SELECT 1 FROM pg_depend d
                WHERE d.objid = c.oid AND d.deptype IN ('a', 'i'))
    LOOP
        EXECUTE format('ALTER SEQUENCE public.%I OWNER TO ansiauth_app', r.relname);
    END LOOP;

    FOR r IN
        SELECT p.oid::regprocedure AS firma
          FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
         WHERE n.nspname = 'public'
    LOOP
        EXECUTE format('ALTER ROUTINE %s OWNER TO ansiauth_app', r.firma);
    END LOOP;

    FOR r IN
        SELECT t.typname
          FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
         WHERE n.nspname = 'public' AND t.typtype IN ('e', 'd')
    LOOP
        EXECUTE format('ALTER TYPE public.%I OWNER TO ansiauth_app', r.typname);
    END LOOP;
END
$$;

-- 4. Verificacion: no debe quedar ningun objeto de ``public`` con otro dueno,
--    y el rol no puede saltear RLS.
SELECT c.relname AS objeto_con_otro_dueno, pg_get_userbyid(c.relowner) AS dueno
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = 'public' AND c.relowner <> 'ansiauth_app'::regrole;

SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = 'ansiauth_app';
