package widgets

import "fmt"
import (
	f "fmt"
	_ "embed"
	. "errors"
	"io"
)

const Pi = 3.14

var (
	Counter = 0
	Name    = "widgets"
)

type Frobnicator struct {
	Items []string
}

type ItemList = []string

func New() *Frobnicator {
	return &Frobnicator{}
}

func (f *Frobnicator) Run() error {
	return nil
}

func (f Frobnicator) Render() string {
	return "frob"
}

func Helper(x int) int {
	fmt.Println(x)
	return x + 1
}
