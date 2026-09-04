package org.throwgen.core;

import com.github.javaparser.ast.NodeList;
import com.github.javaparser.ast.stmt.BlockStmt;
import com.github.javaparser.ast.stmt.Statement;
import com.github.javaparser.ast.stmt.SwitchEntry;
import com.github.javaparser.ast.stmt.SwitchStmt;
import com.github.javaparser.ast.visitor.Visitable;

public class SwitchThrowRemover extends ThrowRemover {

    private void handleSwitchEntries(NodeList<SwitchEntry> entries) {
        NodeList<SwitchEntry> toRemove = new NodeList<>();
        NodeList<SwitchEntry> fallThrough = new NodeList<>();
        for (SwitchEntry ent : entries) {
            if (ent.getStatements().size() > 0) {
                if (ent.getStatement(0).isThrowStmt()) {
                    System.out.println("![switch-throw]!");
                    toRemove.add(ent);
                    for (SwitchEntry fEntry : fallThrough) {
                        toRemove.add(fEntry);
                    }
                }
                fallThrough = new NodeList<>();
            } else {
                fallThrough.add(ent);
            }
        }
        for (SwitchEntry rEnt : toRemove) {
            entries.remove(rEnt);
        }
    }

    public Visitable visit(SwitchStmt n, Void arg) {
        Visitable out = super.visit(n, arg);
        SwitchStmt switchStmt = (SwitchStmt)out;
        Statement swtichParent = (Statement)switchStmt.getParentNode().get();

        handleSwitchEntries(switchStmt.getEntries());
        NodeList<SwitchEntry> newEntries = switchStmt.getEntries();
        if (newEntries.size() > 1) {
            switchStmt.setEntries(newEntries);
            return switchStmt;
        } else if (newEntries.size() == 1) {
            // remove break statement
            Statement lastStmt = newEntries.get(0).getStatement(
                newEntries.get(0).getStatements().size() - 1);
            if (lastStmt.isBreakStmt()) {
                lastStmt.remove();
            }
            if (swtichParent.isBlockStmt()) {
                // if outside is a block take all statments out
                int start = swtichParent.asBlockStmt().getStatements().indexOf(
                    switchStmt);
                takeStmtOut(newEntries.get(0).getStatements(),
                            swtichParent.asBlockStmt(), start);
                return null;
            } else {
                // if outside is not return as a block statement
                return new BlockStmt(newEntries.get(0).getStatements());
            }
        } else {
            return null;
        }
    }
}
