package org.throwgen.core;

import com.github.javaparser.ast.stmt.IfStmt;
import com.github.javaparser.ast.stmt.SwitchEntry;
import com.github.javaparser.ast.stmt.Statement;
import com.github.javaparser.ast.visitor.Visitable;

public class IfThrowRemover extends ThrowRemover {
    private Visitable handleThen(Statement thenStmt, IfStmt ifStmt) {
        if (ifStmt.getParentNode().get() instanceof SwitchEntry) {
            ifStmt.getParentNode().get().remove();
            return null;
        }
        Statement ifParent = (Statement)ifStmt.getParentNode().get();
        if (ifStmt.getElseStmt().isPresent()) {
            Statement elseStmt = ifStmt.getElseStmt().get();
            if (!elseStmt.isThrowStmt()) {
                // if there is an else statement and it is not a throw
                // then we take the else statement out
                if (elseStmt.isBlockStmt()) {
                    if (ifParent.isBlockStmt()) {
                        // if parent of if is a block statement then
                        // put each stmt in thorw in and remove if
                        int start =
                            ifParent.asBlockStmt().getStatements().indexOf(
                                ifStmt);
                        takeStmtOut(elseStmt.asBlockStmt(),
                                    ifParent.asBlockStmt(), start);
                        return null;
                    } else {
                        // if parent not a throw statement then just
                        // replace if with the else stmt
                        return elseStmt;
                    }
                }
                else{
                    return elseStmt;
                }
            }
        }
         // don't care about if else is also throw
        return null;

    }

    public Visitable visit(IfStmt n, Void arg) {
        Visitable out = super.visit(n, arg);
        Statement thenStmt = n.getThenStmt();
        if (thenStmt.isThrowStmt()) {
            System.out.println("![if-throw]!");
            out = handleThen(thenStmt, (IfStmt) out);
        } else if (n.getElseStmt().isPresent()) {
            System.out.println("![if-throw]!");
            Statement elseStmt = n.getElseStmt().get();
            if (elseStmt.isThrowStmt()) {
                // if else statement is throw then just remove
                ((IfStmt) out).removeElseStmt();
            }
        }
        return out;
    }
}
