// helmrender – offline renderer for this repository's Helm charts (Stage 6 local validation only).
//
// It uses Go's text/template, the engine Helm itself uses, with the subset of Helm/Sprig functions the charts in
// helm/charts are allowed to use (see FUNCS below). It is NOT Helm: no hooks ordering, no lookup, no CRD handling,
// no schema validation (done in Python with jsonschema). `helm lint` / `helm template` remain validation items.
//
// Usage: helmrender <context.json> <template-file>...
//
//	context.json = {"Values": {...}, "Release": {"Name": "...", "Namespace": "..."}, "Chart": {"Name": "...", ...}}
//	files whose base name starts with "_" only define templates; every other file is rendered.
package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"text/template"
)

func toYAML(v interface{}, indent int) string {
	var b strings.Builder
	writeYAML(&b, v, indent, false)
	return strings.TrimRight(b.String(), "\n")
}

func scalar(v interface{}) string {
	switch t := v.(type) {
	case nil:
		return "null"
	case bool:
		return strconv.FormatBool(t)
	case float64:
		if t == float64(int64(t)) {
			return strconv.FormatInt(int64(t), 10)
		}
		return strconv.FormatFloat(t, 'f', -1, 64)
	case int:
		return strconv.Itoa(t)
	case string:
		q, _ := json.Marshal(t)
		return string(q)
	}
	q, _ := json.Marshal(v)
	return string(q)
}

func writeYAML(b *strings.Builder, v interface{}, ind int, inList bool) {
	pad := strings.Repeat(" ", ind)
	switch t := v.(type) {
	case map[string]interface{}:
		if len(t) == 0 {
			b.WriteString("{}\n")
			return
		}
		keys := make([]string, 0, len(t))
		for k := range t {
			keys = append(keys, k)
		}
		sort.Strings(keys)
		for i, k := range keys {
			p := pad
			if inList && i == 0 {
				p = ""
			}
			child := t[k]
			switch c := child.(type) {
			case map[string]interface{}:
				if len(c) == 0 {
					fmt.Fprintf(b, "%s%s: {}\n", p, scalar(k))
				} else {
					fmt.Fprintf(b, "%s%s:\n", p, scalar(k))
					writeYAML(b, c, ind+2, false)
				}
			case []interface{}:
				if len(c) == 0 {
					fmt.Fprintf(b, "%s%s: []\n", p, scalar(k))
				} else {
					fmt.Fprintf(b, "%s%s:\n", p, scalar(k))
					writeYAML(b, c, ind, false)
				}
			default:
				fmt.Fprintf(b, "%s%s: %s\n", p, scalar(k), scalar(c))
			}
		}
	case []interface{}:
		for _, item := range t {
			switch c := item.(type) {
			case map[string]interface{}:
				if len(c) == 0 {
					fmt.Fprintf(b, "%s- {}\n", pad)
				} else {
					fmt.Fprintf(b, "%s- ", pad)
					writeYAML(b, c, ind+2, true)
				}
			case []interface{}:
				fmt.Fprintf(b, "%s- %s\n", pad, scalar(c))
			default:
				fmt.Fprintf(b, "%s- %s\n", pad, scalar(c))
			}
		}
	default:
		fmt.Fprintf(b, "%s%s\n", pad, scalar(t))
	}
}

func indentText(n int, s string) string {
	pad := strings.Repeat(" ", n)
	return pad + strings.ReplaceAll(s, "\n", "\n"+pad)
}

func empty(v interface{}) bool {
	switch t := v.(type) {
	case nil:
		return true
	case string:
		return t == ""
	case bool:
		return !t
	case float64:
		return t == 0
	case map[string]interface{}:
		return len(t) == 0
	case []interface{}:
		return len(t) == 0
	}
	return false
}

func main() {
	if len(os.Args) < 3 {
		fmt.Fprintln(os.Stderr, "usage: helmrender <context.json> <template-file>...")
		os.Exit(2)
	}
	raw, err := os.ReadFile(os.Args[1])
	if err != nil {
		panic(err)
	}
	var ctx map[string]interface{}
	if err := json.Unmarshal(raw, &ctx); err != nil {
		panic(err)
	}
	root := template.New("root").Option("missingkey=default")
	// FUNCS: the only functions chart templates may use
	funcs := template.FuncMap{
		"toYaml":  func(v interface{}) string { return toYAML(v, 0) },
		"nindent": func(n int, s string) string { return "\n" + indentText(n, s) },
		"indent":  indentText,
		"quote":   func(v interface{}) string { return strconv.Quote(fmt.Sprint(v)) },
		"default": func(d interface{}, v ...interface{}) interface{} {
			if len(v) == 0 || empty(v[0]) {
				return d
			}
			return v[0]
		},
		"required": func(msg string, v interface{}) (interface{}, error) {
			if empty(v) {
				return nil, fmt.Errorf("%s", msg)
			}
			return v, nil
		},
		"trunc": func(n int, s string) string {
			if len(s) > n {
				return s[:n]
			}
			return s
		},
		"trimSuffix": func(suf, s string) string { return strings.TrimSuffix(s, suf) },
		"lower":      strings.ToLower,
		"upper":      strings.ToUpper,
		"replace":    func(old, new, s string) string { return strings.ReplaceAll(s, old, new) },
		"hasPrefix":  func(p, s string) bool { return strings.HasPrefix(s, p) },
		"contains":   func(sub, s string) bool { return strings.Contains(s, sub) },
		"join": func(sep string, l []interface{}) string {
			parts := make([]string, len(l))
			for i, x := range l {
				parts[i] = fmt.Sprint(x)
			}
			return strings.Join(parts, sep)
		},
		"toString":  func(v interface{}) string { return fmt.Sprint(v) },
		"empty":     empty,
		"hasKey":    func(m map[string]interface{}, k string) bool { _, ok := m[k]; return ok },
		"sha256sum": func(s string) string { h := sha256.Sum256([]byte(s)); return hex.EncodeToString(h[:]) },
		"dict": func(kv ...interface{}) map[string]interface{} {
			m := map[string]interface{}{}
			for i := 0; i+1 < len(kv); i += 2 {
				m[fmt.Sprint(kv[i])] = kv[i+1]
			}
			return m
		},
		"list": func(v ...interface{}) []interface{} { return v },
		"include": func(name string, data interface{}) (string, error) {
			var buf bytes.Buffer
			t := root.Lookup(name)
			if t == nil {
				return "", fmt.Errorf("template %q not defined", name)
			}
			err := t.Execute(&buf, data)
			return buf.String(), err
		},
	}
	root.Funcs(funcs)
	var render []string
	for _, f := range os.Args[2:] {
		src, err := os.ReadFile(f)
		if err != nil {
			panic(err)
		}
		if _, err := root.New(f).Parse(string(src)); err != nil {
			fmt.Fprintf(os.Stderr, "parse %s: %v\n", f, err)
			os.Exit(1)
		}
		if !strings.HasPrefix(filepath.Base(f), "_") {
			render = append(render, f)
		}
	}
	for _, f := range render {
		var buf bytes.Buffer
		if err := root.Lookup(f).Execute(&buf, ctx); err != nil {
			fmt.Fprintf(os.Stderr, "render %s: %v\n", f, err)
			os.Exit(1)
		}
		out := strings.TrimSpace(buf.String())
		if out != "" {
			fmt.Printf("---\n# Source: %s\n%s\n", filepath.Base(f), out)
		}
	}
}
