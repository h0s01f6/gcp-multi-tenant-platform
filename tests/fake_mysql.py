"""A small PRIVILEGE MODEL of MySQL 8.4, used only by unit tests.

It is not MySQL. It implements just enough of the privilege rules to execute the SQL that tools/db/grants.py
generates and the probes that tools/db/isotest.py sends, so that tests can show:
  * the generated grants pass ISO-01..10 in the model, and
  * deliberately broken grants (unescaped name, cross-tenant grant, global privilege, extra account) FAIL.
Real behaviour is validated by the cloud tests T-M2/T-M4/T-M9/T-M10.
"""
import itertools
import re

from tools.db.isotest import ConnectRefused, DbError

DB_PRIVS = {"SELECT", "INSERT", "UPDATE", "DELETE", "EXECUTE", "CREATE", "ALTER", "DROP", "INDEX", "REFERENCES",
            "CREATE VIEW", "SHOW VIEW", "TRIGGER", "CREATE ROUTINE", "ALTER ROUTINE", "EVENT", "LOCK TABLES",
            "CREATE TEMPORARY TABLES", "GRANT OPTION"}


def like(pattern, name):
    """MySQL grant-pattern match: `_` one char, `%` any, `\\_`/`\\%` literal."""
    rx, i = "", 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "\\" and i + 1 < len(pattern):
            rx += re.escape(pattern[i + 1]); i += 2; continue
        rx += "." if ch == "_" else ".*" if ch == "%" else re.escape(ch)
        i += 1
    return re.fullmatch(rx, name) is not None


class FakeMySQL:
    _ids = itertools.count(100)

    def __init__(self, name, env):
        self.name, self.env = name, env
        self.dbs = {"mysql", "information_schema", "performance_schema", "sys"}
        self.accounts = {}            # name -> {"roles": set, "global": set, "db": [(pattern, set)], "is_role": bool}
        self.threads = {}             # id -> user
        self.views = set()

    # ------------- setup -------------
    def add_user(self, user):
        self.accounts.setdefault(user, {"roles": set(), "global": set(), "db": [], "is_role": False})

    def apply_script(self, sql):
        for stmt in [s.strip() for s in re.sub(r"--[^\n]*", "", sql).split(";") if s.strip()]:
            self.admin_exec(stmt)

    def admin_exec(self, stmt):
        if m := re.match(r"CREATE DATABASE IF NOT EXISTS `([^`]+)`", stmt):
            self.dbs.add(m.group(1))
        elif m := re.match(r"CREATE ROLE IF NOT EXISTS '([^']+)'", stmt):
            self.accounts.setdefault(m.group(1), {"roles": set(), "global": set(), "db": [], "is_role": True})
        elif m := re.match(r"GRANT (.+) ON (\*|`[^`]+`)\.\* TO '([^']+)'", stmt):
            privs = {p.strip() for p in m.group(1).split(",")}
            target = self.accounts[m.group(3)]
            if m.group(2) == "*":
                target["global"] |= privs
            else:
                target["db"].append((m.group(2).strip("`"), privs))
        elif m := re.match(r"GRANT ((?:'[^']+'\s*,?\s*)+) TO '([^']+)'@'%'", stmt):
            for r in re.findall(r"'([^']+)'", m.group(1)):
                self.accounts[m.group(2)]["roles"].add(r)
        elif stmt.startswith(("SET DEFAULT ROLE", "ALTER USER", "CREATE TABLE IF NOT EXISTS")):
            pass
        elif m := re.match(r"DROP USER IF EXISTS '([^']+)'", stmt):
            self.accounts.pop(m.group(1), None)
        elif stmt.startswith(("DROP DATABASE IF EXISTS", "DROP TABLE IF EXISTS", "DROP VIEW IF EXISTS")):
            pass
        else:
            raise NotImplementedError(stmt)

    # ------------- privilege evaluation -------------
    def effective(self, user):
        acc = self.accounts[user]
        glob, db = set(acc["global"]), list(acc["db"])
        for r in acc["roles"]:
            glob |= self.accounts[r]["global"]
            db += self.accounts[r]["db"]
        return glob, db

    def db_privs(self, user, database):
        glob, db = self.effective(user)
        out = {p for p in glob if p in DB_PRIVS or p == "ALL"}
        for pat, privs in db:
            if like(pat, database):
                out |= privs
        if "ALL" in out:
            out |= DB_PRIVS
        return out

    def show_grants(self, user):
        acc = self.accounts.get(user)
        if acc is None:
            raise DbError(1141, "no such grant")
        lines = [f"GRANT {', '.join(sorted(acc['global'])) or 'USAGE'} ON *.* TO `{user}`@`%`"]
        for pat, privs in acc["db"]:
            lines.append(f"GRANT {', '.join(sorted(privs))} ON `{pat}`.* TO `{user}`@`%`")
        if acc["roles"]:
            lines.append(f"GRANT {','.join(f'`{r}`@`%`' for r in sorted(acc['roles']))} TO `{user}`@`%`")
        return [(l,) for l in lines]


class Session:
    def __init__(self, server, user, admin=False):
        self.server, self.user, self.admin = server, user, admin
        self.connection_id = next(FakeMySQL._ids)
        server.threads[self.connection_id] = user

    def close(self):
        self.server.threads.pop(self.connection_id, None)

    def execute(self, sql):
        s, srv, u = sql.strip(), self.server, self.user
        if self.admin:
            if m := re.match(r"SHOW GRANTS FOR '([^']+)'@'%'", s):
                return srv.show_grants(m.group(1))
            if s.startswith("SELECT user FROM mysql.user"):
                return [(a,) for a in srv.accounts] + [("root",), ("cloudsqlsuperuser",), ("sqlboot-prd",)]
            srv.admin_exec(s)
            return []
        glob, _ = srv.effective(u)
        if m := re.match(r"USE `([^`]+)`", s):
            if not srv.db_privs(u, m.group(1)):
                raise DbError(1044, f"Access denied for user '{u}' to database '{m.group(1)}'")
            return []
        if s == "SHOW DATABASES":
            return [(d,) for d in sorted(srv.dbs) if d == "information_schema" or srv.db_privs(u, d)]
        if s == "SHOW PROCESSLIST":
            return [(i, who) for i, who in srv.threads.items() if who == u or "PROCESS" in glob or "ALL" in glob]
        if m := re.match(r"SELECT id FROM `([^`]+)`\.`canary`", s) or re.match(r"SELECT user FROM (mysql)\.user", s):
            if "SELECT" not in srv.db_privs(u, m.group(1)):
                raise DbError(1142, "SELECT command denied")
            return []
        if m := re.match(r"CREATE TABLE `([^`]+)`\.", s):
            if "CREATE" not in srv.db_privs(u, m.group(1)):
                raise DbError(1142, "CREATE command denied")
            return []
        if m := re.match(r"DROP TABLE IF EXISTS `([^`]+)`\.", s):
            if "DROP" not in srv.db_privs(u, m.group(1)):
                raise DbError(1142, "DROP command denied")
            return []
        if m := re.match(r"CREATE DATABASE `([^`]+)`", s):
            if "CREATE" not in srv.db_privs(u, m.group(1)):
                raise DbError(1044, "Access denied")
            return []
        if s.startswith("CREATE USER"):
            if not glob & {"CREATE USER", "ALL"}:
                raise DbError(1227, "need CREATE USER")
            return []
        if m := re.match(r"GRANT .+ ON `([^`]+)`\.\*", s):
            if "GRANT OPTION" not in srv.db_privs(u, m.group(1)):
                raise DbError(1044, "Access denied")
            return []
        if s.startswith("SET GLOBAL"):
            if not glob & {"SYSTEM_VARIABLES_ADMIN", "SUPER", "ALL"}:
                raise DbError(1227, "need SYSTEM_VARIABLES_ADMIN")
            return []
        if m := re.match(r"KILL QUERY (\d+)", s):
            if srv.threads.get(int(m.group(1))) != u and not glob & {"CONNECTION_ADMIN", "SUPER", "ALL"}:
                raise DbError(1095, "You are not owner of thread")
            return []
        if m := re.match(r"CREATE DEFINER=`([^`]+)`@`%` VIEW `([^`]+)`\.", s):
            if "CREATE VIEW" not in srv.db_privs(u, m.group(2)):
                raise DbError(1142, "CREATE VIEW denied")
            if m.group(1) != u and not glob & {"SET_USER_ID", "SET_ANY_DEFINER", "SUPER", "ALL"}:
                raise DbError(1227, "need SET_ANY_DEFINER")
            return []
        raise NotImplementedError(s)


class FakeFleet:
    """Pools keyed by name; connect() enforces the tier boundary like IAM groups + VPC separation would."""

    def __init__(self, servers, probe_tier):
        self.servers, self.probe_tier = servers, probe_tier
        self.tier_boundary = True

    def connect(self, pool, user):
        srv = self.servers.get(pool)
        if srv is None:
            raise ConnectRefused(f"no such pool {pool}")
        if self.tier_boundary and (srv.env == "prd") != (self.probe_tier == "prd"):
            raise ConnectRefused("not in the tier's connect group / no route from this VPC")
        if user not in srv.accounts or srv.accounts[user]["is_role"]:
            raise DbError(1045, f"Access denied for user '{user}'")
        return Session(srv, user)


class FakeAdmin:
    def __init__(self, servers):
        self.servers = servers

    def connect(self, pool, user):
        return Session(self.servers[pool], "sqlboot", admin=True)
